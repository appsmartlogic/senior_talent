"""
Servicios de IA — extracción de datos del CV con Ollama.
El PDF se procesa en memoria y nunca se guarda en disco.
"""
import io
import json
import re
import requests
from django.conf import settings


def extraer_texto_pdf(contenido_bytes: bytes) -> str:
    """Extrae texto solo de las primeras 2 páginas del PDF."""
    try:
        import pypdf
        lector = pypdf.PdfReader(io.BytesIO(contenido_bytes))
        paginas = lector.pages[:2]
        texto = '\n'.join(
            pagina.extract_text() or '' for pagina in paginas
        )
        texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ', texto)
        texto = re.sub(r' +', ' ', texto)
        return texto.strip()
    except Exception as e:
        raise ValueError(f'No se pudo leer el PDF: {e}')


def extraer_datos_cv(contenido_bytes: bytes) -> dict:
    """
    Recibe el PDF en bytes, extrae texto y llama a Ollama
    para estructurar los datos. Devuelve un dict limpio.
    """
    texto = extraer_texto_pdf(contenido_bytes)

    if len(texto) < 100:
        raise ValueError('El PDF no contiene suficiente texto legible.')

    prompt = f"""You are a professional CV/resume data extractor. You work with CVs in Spanish and English.
Analyze the following CV text and extract the data in JSON format.
IMPORTANT: Respond ONLY with the JSON, no explanations, no markdown, no extra text.
All response values must be in the SAME language as the CV text.

For "cargo_actual": look for the most recent or prominent job title. Examples: Lider, Director, Gerente, Developer, Lead, Manager, Analista, Jefe, Coordinator, Scrum Master. If not found use the first title mentioned.
For "años_experiencia": return only a number, not text.

CV text:
{texto[:2000]}

Return exactly this JSON:
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

    try:
        resp = requests.post(
            f'{settings.OLLAMA_URL}/api/generate',
            json={
                'model': settings.OLLAMA_MODEL,
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.1},
            },
            timeout=180,
        )
        resp.raise_for_status()
        respuesta_raw = resp.json().get('response', '{}')
        datos = _parsear_json_seguro(respuesta_raw)
        return _limpiar_datos(datos)
    except requests.RequestException as e:
        raise ValueError(f'Error conectando con Ollama: {e}')


def _parsear_json_seguro(texto: str) -> dict:
    """Intenta parsear JSON aunque el modelo agregue texto extra."""
    texto = texto.strip()
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _limpiar_datos(datos: dict) -> dict:
    """Valida y limpia los datos extraídos por la IA."""
    años = int(datos.get('años_experiencia', 0) or 0)

    if años == 0 and datos.get('experiencias'):
        import datetime
        año_actual = datetime.date.today().year
        for exp in datos['experiencias']:
            inicio = exp.get('año_inicio', 0) or 0
            fin    = exp.get('año_fin') or año_actual
            if inicio > 1950:
                años += max(0, fin - inicio)

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