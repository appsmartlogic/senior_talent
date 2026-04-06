"""
Servicios de IA — extracción de datos del CV con Google Gemini Flash.
El PDF se procesa en memoria y nunca se guarda en disco.
"""
import io
import json
import re
import datetime
import requests
from django.conf import settings


def extraer_texto_pdf(contenido_bytes: bytes) -> str:
    """Extrae texto de las primeras 3 páginas del PDF usando pdfplumber."""
    try:
        import pdfplumber
        texto_total = []
        with pdfplumber.open(io.BytesIO(contenido_bytes)) as pdf:
            for pagina in pdf.pages[:3]:
                texto = pagina.extract_text(x_tolerance=3, y_tolerance=3)
                if texto:
                    texto_total.append(texto)
        texto = '\n'.join(texto_total)
        texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ', texto)
        texto = re.sub(r' +', ' ', texto)
        return texto.strip()
    except Exception as e:
        raise ValueError(f'No se pudo leer el PDF: {e}')


def extraer_datos_cv(contenido_bytes: bytes) -> dict:
    """
    Recibe el PDF en bytes, extrae texto y llama a Gemini Flash
    para estructurar los datos. Devuelve un dict limpio y validado.
    """
    texto = extraer_texto_pdf(contenido_bytes)

    if len(texto) < 100:
        raise ValueError('El PDF no contiene suficiente texto legible.')

    prompt = f"""You are a data extraction assistant for a professional talent platform.
Your job is to extract specific information from any CV/resume text, regardless of its format, language or structure.

IMPORTANT: Respond ONLY with valid JSON. No explanations, no markdown, no extra text.

Extract the following fields from the CV:

1. "nombre": Full name of the person. Look anywhere in the document.
2. "cargo_actual": Most recent or current job title. If not found, use their main professional specialty.
3. "ciudad": City where the person is located.
4. "pais_codigo": 2-letter country code (CO=Colombia, MX=Mexico, AR=Argentina, ES=Spain, VE=Venezuela, PE=Peru, CL=Chile, EC=Ecuador, US=United States, etc).
5. "años_experiencia": Total years of professional experience as a number only. Count from the earliest work/project date to today.
6. "resumen": Professional summary of 2-3 sentences. Use the profile/summary section if exists, otherwise create one based on the CV content.
7. "habilidades": List of technical and soft skills. Look in ANY section: skills, competencies, tools, technologies, certifications, or extract from experience descriptions.
8. "idiomas": List of languages with proficiency level. If not explicitly mentioned, assume Spanish native for Latin American CVs.
9. "experiencias": ALL professional activities with dates: jobs, projects, research, entrepreneurship, freelance. Include everything with a date range.
10. "educacion": "titulo" = degree name (TSU, Licenciatura, Ingenieria, MBA, etc). "institucion" = university or school name. NEVER swap these two fields.

CV text to analyze:
{texto[:5000]}

Return exactly this JSON structure:
{{
  "nombre": "",
  "cargo_actual": "",
  "ciudad": "",
  "pais_codigo": "",
  "años_experiencia": 0,
  "resumen": "",
  "habilidades": [],
  "idiomas": [
    {{"idioma": "", "nivel": "nativo|avanzado|intermedio|basico"}}
  ],
  "experiencias": [
    {{"empresa": "", "cargo": "", "año_inicio": 0, "año_fin": null, "descripcion": ""}}
  ],
  "educacion": [
    {{"titulo": "", "institucion": "", "año_fin": null}}
  ]
}}"""

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError('GEMINI_API_KEY no configurada.')

    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.1,
            'maxOutputTokens': 4096,
        }
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        resultado = resp.json()
        respuesta_raw = (
            resultado
            .get('candidates', [{}])[0]
            .get('content', {})
            .get('parts', [{}])[0]
            .get('text', '{}')
        )
        datos = _parsear_json_seguro(respuesta_raw)
        datos_limpios = _limpiar_datos(datos)
        return _validar_experiencia(datos_limpios)
    except requests.RequestException as e:
        raise ValueError(f'Error conectando con Gemini: {e}')


def _parsear_json_seguro(texto: str) -> dict:
    """Intenta parsear JSON aunque el modelo agregue texto extra."""
    texto = texto.strip()
    texto = re.sub(r'^```json|^```|```$', '', texto, flags=re.MULTILINE).strip()
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _calcular_años_reales(experiencias: list) -> int:
    """Calcula años reales sin contar solapamientos dobles."""
    año_actual = datetime.date.today().year
    periodos = []
    for exp in experiencias:
        inicio = exp.get('año_inicio', 0) or 0
        fin = exp.get('año_fin') or año_actual
        if not (1950 < inicio <= año_actual):
            continue
        if not (inicio <= fin <= año_actual + 1):
            fin = año_actual
        periodos.append((inicio, fin))
    if not periodos:
        return 0
    periodos.sort(key=lambda x: x[0])
    fusionados = [periodos[0]]
    for inicio, fin in periodos[1:]:
        ultimo_inicio, ultimo_fin = fusionados[-1]
        if inicio <= ultimo_fin:
            fusionados[-1] = (ultimo_inicio, max(ultimo_fin, fin))
        else:
            fusionados.append((inicio, fin))
    total = sum(fin - inicio for inicio, fin in fusionados)
    return min(total, 60)


def _validar_experiencia(datos: dict) -> dict:
    """Valida años de experiencia contra experiencia laboral real."""
    experiencias = datos.get('experiencias', [])
    años_declarados = datos.get('años_experiencia', 0)
    años_calculados = _calcular_años_reales(experiencias)
    if años_calculados > 0:
        diferencia = abs(años_declarados - años_calculados)
        if diferencia > 3:
            datos['años_experiencia'] = años_calculados
            datos['_alerta_experiencia'] = (
                f'Años declarados ({años_declarados}) difieren '
                f'de años calculados ({años_calculados}). '
                f'Se usó el valor calculado.'
            )
        elif años_declarados == 0:
            datos['años_experiencia'] = años_calculados
    return datos


def _limpiar_datos(datos: dict) -> dict:
    """Valida y limpia los datos extraídos por la IA."""
    años = int(datos.get('años_experiencia', 0) or 0)
    habilidades = datos.get('habilidades', [])
    if isinstance(habilidades, str):
        habilidades = [h.strip() for h in habilidades.split(',') if h.strip()]
    return {
        'nombre':           str(datos.get('nombre', '')).strip()[:200],
        'cargo_actual':     str(datos.get('cargo_actual', '') or '').strip()[:200],
        'ciudad':           str(datos.get('ciudad', '')).strip()[:100],
        'pais_codigo':      str(datos.get('pais_codigo', '')).strip().upper()[:2],
        'años_experiencia': min(años, 60),
        'resumen':          str(datos.get('resumen', '')).strip()[:2000],
        'habilidades':      [str(h).strip()[:50] for h in habilidades[:12]],
        'idiomas':          datos.get('idiomas', []),
        'experiencias':     datos.get('experiencias', []),
        'educacion':        datos.get('educacion', []),
    }