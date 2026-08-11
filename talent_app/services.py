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

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.1,
            'maxOutputTokens': 4096,
        }
    }

    MODELOS_GEMINI = [
        'gemini-flash-latest',
        'gemini-2.0-flash',
        'gemini-1.5-flash',
    ]

    resp = None
    ultimo_error = None

    for modelo in MODELOS_GEMINI:
        try:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}'
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            ultimo_error = e
            continue

    if resp is None or not resp.ok:
        raise ValueError('Error conectando con Gemini. Todos los modelos fallaron.')

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


# ══════════════════════════════════════════════════════════════
# OFERTAS LABORALES AUTOMÁTICAS — SerpAPI + Gemini
# Funciones completamente nuevas, no modifican nada existente.
# ══════════════════════════════════════════════════════════════
import re as _re
import logging as _logging
_logger_ofertas = _logging.getLogger('talent_app')

# Mapeo país → parámetros SerpAPI
_PAIS_SERP = {
    # América del Sur
    'CO': ('co', 'Colombia'),
    'VE': ('ve', 'Venezuela'),
    'AR': ('ar', 'Argentina'),
    'CL': ('cl', 'Chile'),
    'PE': ('pe', 'Perú'),
    'EC': ('ec', 'Ecuador'),
    'BR': ('br', 'Brasil'),
    'BO': ('bo', 'Bolivia'),
    'PY': ('py', 'Paraguay'),
    'UY': ('uy', 'Uruguay'),
    'GY': ('gy', 'Guyana'),
    'SR': ('sr', 'Surinam'),
    # América Central
    'PA': ('pa', 'Panamá'),
    'CR': ('cr', 'Costa Rica'),
    'GT': ('gt', 'Guatemala'),
    'HN': ('hn', 'Honduras'),
    'SV': ('sv', 'El Salvador'),
    'NI': ('ni', 'Nicaragua'),
    'BZ': ('bz', 'Belice'),
    # El Caribe
    'CU': ('cu', 'Cuba'),
    'DO': ('do', 'República Dominicana'),
    'PR': ('pr', 'Puerto Rico'),
    'HT': ('ht', 'Haití'),
    'JM': ('jm', 'Jamaica'),
    'TT': ('tt', 'Trinidad y Tobago'),
    # América del Norte
    'MX': ('mx', 'México'),
    'US': ('us', 'United States'),
    'CA': ('ca', 'Canadá'),
    # Europa hispanohablante
    'ES': ('es', 'España'),
    # Fallback global
    'XX': ('us', 'Global'),
}

def _traducir_cargo_gemini(cargo: str, api_key: str) -> str:
    """
    Usa Gemini para traducir el cargo al inglés de forma dinámica.
    Sin diccionarios quemados — funciona con cualquier cargo nuevo.
    Fallback a extracción de palabras clave si Gemini falla.
    """
    import requests as _req

    try:
        # Obtener modelos disponibles dinámicamente
        url_modelos = f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}'
        r = _req.get(url_modelos, timeout=8)
        r.raise_for_status()
        modelos = r.json().get('models', [])
        EXCLUIR = ['tts', 'image', 'preview', 'nano', 'research', 'omni', 'lyria', 'customtools']
        modelos_aptos = [
            m['name'].replace('models/', '')
            for m in modelos
            if 'generateContent' in m.get('supportedGenerationMethods', [])
            and any(x in m['name'] for x in ['flash', 'pro'])
            and not any(x in m['name'] for x in EXCLUIR)
            and 'vision' not in m['name']
            and 'embedding' not in m['name']
        ]
        modelos_aptos.sort(key=lambda n: (0 if 'lite' in n else 1 if 'flash' in n else 2))
        modelo = modelos_aptos[0] if modelos_aptos else 'gemini-flash-lite-latest'

        prompt = (
            f'Translate this job title to English for a job search query. '
            f'Return ONLY 2-4 keywords in English, no explanation:\n{cargo}'
        )
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}'
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 20},
        }
        resp = _req.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        resultado = (
            resp.json()
            .get('candidates', [{}])[0]
            .get('content', {})
            .get('parts', [{}])[0]
            .get('text', '')
            .strip()
            .replace('"', '')
            .replace("'", '')
        )
        if resultado and len(resultado.split()) <= 6:
            _logger_ofertas.info(f'_traducir_cargo_gemini: "{cargo}" → "{resultado}"')
            return resultado
    except Exception as e:
        _logger_ofertas.warning(f'_traducir_cargo_gemini: falló ({e}), usando fallback')

    # Fallback — extraer palabras en inglés o acrónimos del cargo original
    cargo_limpio = _re.sub(r'[/|,\-]', ' ', cargo).strip()
    palabras = [p for p in cargo_limpio.split() if len(p) > 2]
    en_ingles = [p for p in palabras if any(c.isupper() for c in p[1:])]
    return ' '.join((en_ingles or palabras)[:3])

def _construir_query_oferta(candidato) -> dict:
    """
    Construye query en inglés para SerpAPI — única combinación que da resultados.
    gl=us siempre, sin location — SerpAPI Google Jobs funciona mejor así.
    """
    from talent_app.models import IdiomaCandiato

    modalidad = candidato.modalidad

    # Siempre gl=us, sin location — es lo que da resultados
    gl = 'us'
    location = ''

    # Detectar idioma del candidato
    idiomas_qs = IdiomaCandiato.objects.filter(candidato=candidato)
    idiomas_lista = [i.idioma.lower() for i in idiomas_qs]
    habla_ingles = any('ingl' in i for i in idiomas_lista)

    # Obtener API key de Gemini
    from django.conf import settings as _dj_settings
    gemini_key = _dj_settings.GEMINI_API_KEY

    # Traducir cargo completo con Gemini — dinámico, sin diccionario quemado
    # Procesar cada parte separada por / o | para no perder palabras clave
    partes_cargo = _re.split(r'[/|]', candidato.cargo_actual)
    todas_palabras_en = []
    for parte in partes_cargo:
        traducidas = _traducir_cargo_gemini(parte.strip(), gemini_key)
        if traducidas:
            todas_palabras_en.extend(traducidas.split())

    # Deduplicar manteniendo orden
    vistas = set()
    palabras_unicas = []
    for p in todas_palabras_en:
        if p.lower() not in vistas:
            vistas.add(p.lower())
            palabras_unicas.append(p)
    cargo_en = ' '.join(palabras_unicas[:4])

    # Si cargo quedó vacío usar primera habilidad
    if not cargo_en and candidato.habilidades:
        cargo_en = _traducir_cargo_gemini(candidato.habilidades[0], gemini_key)

    # Nivel de experiencia
    nivel = 'Senior' if candidato.años_experiencia >= 15 else ''

    # Construir query — siempre en inglés con gl=us, única combinación que da resultados
    if modalidad == 'remoto':
        query = f'{cargo_en} {nivel} Remote'.strip()
    else:
        # Presencial o híbrido → buscar en país del candidato en español
        cargo_es = _re.sub(r'[/|,\-]', ' ', candidato.cargo_actual)
        cargo_es = _re.sub(r'\s+', ' ', cargo_es).strip()
        palabras_es = [p for p in cargo_es.split() if len(p) > 3][:2]
        query = ' '.join(palabras_es)
        location = candidato.pais.nombre

    # Limpiar espacios dobles
    query = _re.sub(r'\s+', ' ', query).strip()

    _logger_ofertas.info(
        f'_construir_query_oferta: candidato {candidato.pk} '
        f'cargo_original="{candidato.cargo_actual}" '
        f'query_en="{query}" modalidad="{modalidad}"'
    )

    return {
        'query': query,
        'gl': gl,
        'location': location,
        'modalidad': modalidad,
        'habla_ingles': habla_ingles,
    }

def buscar_ofertas_serpapi(candidato) -> list:
    """
    Busca ofertas reales en SerpAPI Google Jobs para un candidato.
    Retorna lista de hasta 10 ofertas crudas o [] si falla.
    Nunca lanza excepción — falla silenciosamente.
    """
    import requests as _req
    from django.conf import settings as _settings

    try:
        params_query = _construir_query_oferta(candidato)
        api_key = _settings.SERPAPI_API_KEY
        if not api_key:
            _logger_ofertas.error(
                'buscar_ofertas_serpapi: SERPAPI_API_KEY no configurada'
            )
            return []

        params = {
            'engine': 'google_jobs',
            'q': params_query['query'],
            'hl': 'es',
            'gl': params_query['gl'],
            'api_key': api_key,
        }

        # Solo enviar location si tiene valor
        if params_query['location']:
            params['location'] = params_query['location']

        resp = _req.get(
            'https://serpapi.com/search',
            params=params,
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get('jobs_results', [])

        # Si el candidato no habla inglés, filtrar ofertas en español
        if not params_query.get('habla_ingles', False):
            INDICADORES_ES = [
                'colombia', 'méxico', 'mexico', 'argentina', 'chile',
                'perú', 'peru', 'españa', 'espana', 'venezuela',
                'ecuador', 'bolivia', 'paraguay', 'uruguay', 'panamá',
                'panama', 'costa rica', 'guatemala', 'honduras',
                'nicaragua', 'el salvador', 'república dominicana',
                'remoto',  # solo remoto en español, NO 'remote'
            ]
            jobs_filtrados = []
            for j in jobs:
                titulo = j.get('title', '').lower()
                ubicacion = j.get('location', '').lower()
                descripcion = j.get('description', '').lower()[:200]
                texto_completo = f'{titulo} {ubicacion} {descripcion}'
                # Incluir si tiene indicador hispanohablante O si la descripción está en español
                if any(ind in texto_completo for ind in INDICADORES_ES):
                    jobs_filtrados.append(j)
            if jobs_filtrados:
                jobs = jobs_filtrados
                _logger_ofertas.info(
                    f'buscar_ofertas_serpapi: filtrado por idioma español → {len(jobs)} ofertas'
                )

        _logger_ofertas.info(
            f'buscar_ofertas_serpapi: candidato {candidato.pk} '
            f'query="{params_query["query"]}" → {len(jobs)} ofertas'
        )
        return jobs[:10]

    except Exception as e:
        _logger_ofertas.error(
            f'buscar_ofertas_serpapi: candidato {candidato.pk} → {e}'
        )
        return []


def rankear_ofertas_gemini(candidato, ofertas_raw: list) -> list:
    """
    Usa Gemini para seleccionar y rankear las 3 mejores ofertas
    de la lista cruda de SerpAPI según el perfil del candidato.
    Retorna lista de hasta 3 dicts con info limpia para el email.
    Nunca lanza excepción.
    """
    import json as _json
    import requests as _req
    from django.conf import settings as _settings

    if not ofertas_raw:
        return []

    try:
        ofertas_texto = []
        for i, o in enumerate(ofertas_raw[:10]):
            # Limpiar descripción — quitar caracteres que rompen JSON
            desc = o.get('description', '')[:150]
            desc = desc.replace('"', "'").replace('\n', ' ').replace('\r', '').strip()
            ofertas_texto.append(
                f"{i+1}. {o.get('title','')}"
                f" | {o.get('company_name','')}"
                f" | {o.get('location','')}"
                f" | {desc}"
            )

        sectores = ', '.join([s.nombre for s in candidato.sectores.all()])
        habilidades = ', '.join(candidato.habilidades[:5]) if candidato.habilidades else ''

        prompt = (
            'Responde SOLO con JSON válido. Sin markdown. Sin explicaciones.\n'
            'Formato exacto requerido:\n'
            '{{"seleccionadas":[{{"numero":1,"razon_match":"texto"}},{{"numero":2,"razon_match":"texto"}},{{"numero":3,"razon_match":"texto"}}]}}\n\n'
            f'Candidato: {candidato.cargo_actual}, {candidato.años_experiencia} años experiencia, {candidato.pais.nombre}\n'
            f'Sectores: {sectores} | Habilidades: {habilidades}\n\n'
            f'Ofertas:\n' + '\n'.join(ofertas_texto) + '\n\n'
            'Selecciona los 3 mejores números para este candidato y explica en 1 línea en español.'
        )

        api_key = _settings.GEMINI_API_KEY

        def _obtener_modelos_gemini(api_key):
            try:
                url = f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}'
                resp = _req.get(url, timeout=10)
                resp.raise_for_status()
                modelos = resp.json().get('models', [])

                # Excluir modelos con thinking, tts, image, preview, nano, research
                # ya que consumen tokens extra o no son aptos para JSON puro
                EXCLUIR = ['tts', 'image', 'preview', 'nano', 'research',
                           'omni', 'lyria', 'customtools']

                candidatos = [
                    m['name'].replace('models/', '')
                    for m in modelos
                    if 'generateContent' in m.get('supportedGenerationMethods', [])
                    and any(x in m['name'] for x in ['flash', 'pro'])
                    and not any(x in m['name'] for x in EXCLUIR)
                    and 'vision' not in m['name']
                    and 'embedding' not in m['name']
                ]

                # Ordenar: preferir flash-lite > flash > pro (más rápidos y baratos)
                def _orden_modelo(nombre):
                    if 'lite' in nombre:
                        return 0
                    if 'flash' in nombre:
                        return 1
                    return 2

                candidatos.sort(key=_orden_modelo)

                if candidatos:
                    _logger_ofertas.info(
                        f'_obtener_modelos_gemini: {len(candidatos)} modelos aptos → {candidatos[:3]}'
                    )
                    return candidatos
            except Exception as e:
                _logger_ofertas.warning(
                    f'_obtener_modelos_gemini: falló ({e}), usando fallback'
                )
            return [
                'gemini-flash-latest',
                'gemini-flash-lite-latest',
            ]
        MODELOS_RANKING = _obtener_modelos_gemini(api_key)

        resp = None
        texto = '{}'
        for modelo in MODELOS_RANKING:
            try:
                url = (
                    f'https://generativelanguage.googleapis.com/v1beta/models/'
                    f'{modelo}:generateContent?key={api_key}'
                )
                payload = {
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 512},
                }
                resp = _req.post(url, json=payload, timeout=20)
                resp.raise_for_status()
                texto = (
                    resp.json()
                    .get('candidates', [{}])[0]
                    .get('content', {})
                    .get('parts', [{}])[0]
                    .get('text', '{}')
                    .strip()
                    .replace('```json', '')
                    .replace('```', '')
                    .strip()
                )
                if texto and texto != '{}':
                    _logger_ofertas.info(
                        f'rankear_ofertas_gemini: modelo {modelo} OK'
                    )
                    break
            except Exception as e_modelo:
                _logger_ofertas.warning(
                    f'rankear_ofertas_gemini: modelo {modelo} falló → {e_modelo}'
                )
                continue

        resultado = _json.loads(texto)
        seleccionadas = resultado.get('seleccionadas', [])

        ofertas_finales = []
        for sel in seleccionadas[:3]:
            idx = int(sel.get('numero', 1)) - 1
            if 0 <= idx < len(ofertas_raw):
                oferta = ofertas_raw[idx]
                link = ''
                apply_options = oferta.get('apply_options', [])
                if apply_options and isinstance(apply_options, list):
                    link = apply_options[0].get('link', '')
                ofertas_finales.append({
                    'titulo':      oferta.get('title', ''),
                    'empresa':     oferta.get('company_name', ''),
                    'ubicacion':   oferta.get('location', ''),
                    'descripcion': oferta.get('description', '')[:300],
                    'link':        link,
                    'razon_match': sel.get('razon_match', ''),
                    'fecha':       oferta.get('detected_extensions', {}).get('posted_at', ''),
                })

        _logger_ofertas.info(
            f'rankear_ofertas_gemini: candidato {candidato.pk} '
            f'→ {len(ofertas_finales)} ofertas seleccionadas'
        )
        return ofertas_finales

    except Exception as e:
        _logger_ofertas.error(
            f'rankear_ofertas_gemini: candidato {candidato.pk} → {e}'
        )
        # Fallback: las 3 primeras sin ranking
        fallback = []
        for o in ofertas_raw[:3]:
            link = ''
            apply_options = o.get('apply_options', [])
            if apply_options and isinstance(apply_options, list):
                link = apply_options[0].get('link', '')
            fallback.append({
                'titulo':      o.get('title', ''),
                'empresa':     o.get('company_name', ''),
                'ubicacion':   o.get('location', ''),
                'descripcion': o.get('description', '')[:300],
                'link':        link,
                'razon_match': '',
                'fecha':       o.get('detected_extensions', {}).get('posted_at', ''),
            })
        return fallback


# ══════════════════════════════════════════════════════════════
# MOTOR 2 — Adzuna España (español + remoto)
# ══════════════════════════════════════════════════════════════

def buscar_ofertas_adzuna(candidato) -> list:
    """
    Busca ofertas en Adzuna España para candidatos remotos hispanohablantes.
    Adzuna ES tiene ofertas remotas en español para toda Latinoamérica.
    Retorna lista de hasta 10 ofertas o [] si falla.
    Nunca lanza excepción.
    """
    import requests as _req
    from django.conf import settings as _settings

    try:
        app_id  = _settings.ADZUNA_APP_ID
        app_key = _settings.ADZUNA_APP_KEY

        if not app_id or not app_key:
            _logger_ofertas.error('buscar_ofertas_adzuna: credenciales no configuradas')
            return []

        # Traducir cargo para Adzuna — usa Gemini igual que SerpAPI
        gemini_key = _settings.GEMINI_API_KEY
        cargo_traducido = _traducir_cargo_gemini(candidato.cargo_actual, gemini_key)
        nivel = 'Senior' if candidato.años_experiencia >= 15 else ''
        query = f'{cargo_traducido} {nivel} remoto'.strip()
        query = _re.sub(r'\s+', ' ', query).strip()

        params = {
            'app_id':          app_id,
            'app_key':         app_key,
            'results_per_page': 10,
            'what':            query,
            'content-type':    'application/json',
        }

        # Adzuna España — mejor cobertura de remoto en español
        url = 'https://api.adzuna.com/v1/api/jobs/es/search/1'

        resp = _req.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        resultados = data.get('results', [])

        # Normalizar al mismo formato que SerpAPI
        jobs = []
        for r in resultados:
            jobs.append({
                'title':        r.get('title', ''),
                'company_name': r.get('company', {}).get('display_name', ''),
                'location':     r.get('location', {}).get('display_name', ''),
                'description':  r.get('description', ''),
                'apply_options': [{'link': r.get('redirect_url', '')}],
                'detected_extensions': {
                    'posted_at': r.get('created', '')[:10] if r.get('created') else '',
                },
            })

        _logger_ofertas.info(
            f'buscar_ofertas_adzuna: candidato {candidato.pk} '
            f'query="{query}" → {len(jobs)} ofertas'
        )
        return jobs

    except Exception as e:
        _logger_ofertas.error(
            f'buscar_ofertas_adzuna: candidato {candidato.pk} → {e}'
        )
        return []

# ══════════════════════════════════════════════════════════════
# MOTOR 3 — Jooble (español + presencial/híbrido, toda Latam)
# ══════════════════════════════════════════════════════════════

def buscar_ofertas_jooble(candidato) -> list:
    """
    Busca ofertas en Jooble para candidatos hispanohablantes presenciales o híbridos.
    Jooble agrega +13,000 fuentes incluyendo computrabajo, elempleo, bumeran.
    Cubre toda Latinoamérica nativamente.
    Retorna lista de hasta 10 ofertas o [] si falla.
    Nunca lanza excepción.
    """
    import json as _json
    import requests as _req
    from django.conf import settings as _settings

    try:
        api_key = _settings.JOOBLE_API_KEY
        if not api_key:
            _logger_ofertas.error('buscar_ofertas_jooble: JOOBLE_API_KEY no configurada')
            return []

        # Construir query en español con cargo limpio
        cargo_limpio = _re.sub(r'[/|,\-]', ' ', candidato.cargo_actual)
        cargo_limpio = _re.sub(r'\s+', ' ', cargo_limpio).strip()
        palabras = [p for p in cargo_limpio.split() if len(p) > 3][:3]
        cargo_base = ' '.join(palabras)
        nivel = 'senior' if candidato.años_experiencia >= 15 else ''
        query = f'{cargo_base} {nivel}'.strip()
        query = _re.sub(r'\s+', ' ', query).strip()

        # Ubicación: ciudad si es presencial, país si es híbrido
        if candidato.modalidad == 'presencial' and candidato.ciudad:
            ubicacion = f'{candidato.ciudad}, {candidato.pais.nombre}'
        else:
            ubicacion = candidato.pais.nombre

        # Jooble funciona mejor con país en keywords que en location
        query_con_pais = f'{query} {candidato.pais.nombre}'.strip()

        payload = {
            'keywords':      query_con_pais,
            'page':          1,
            'resultsOnPage': 10,
        }

        url = f'https://jooble.org/api/{api_key}'
        resp = _req.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        resultados = data.get('jobs', [])

        # Normalizar al mismo formato que SerpAPI y Adzuna
        jobs = []
        for r in resultados:
            jobs.append({
                'title':        r.get('title', ''),
                'company_name': r.get('company', ''),
                'location':     r.get('location', ''),
                'description':  r.get('snippet', ''),
                'apply_options': [{'link': r.get('link', '')}],
                'detected_extensions': {
                    'posted_at': r.get('updated', '')[:10] if r.get('updated') else '',
                },
            })

        _logger_ofertas.info(
            f'buscar_ofertas_jooble: candidato {candidato.pk} '
            f'query="{query_con_pais}" → {len(jobs)} ofertas'
        )
        return jobs

    except Exception as e:
        _logger_ofertas.error(
            f'buscar_ofertas_jooble: candidato {candidato.pk} → {e}'
        )
        return []


# ══════════════════════════════════════════════════════════════
# ORQUESTADOR — selecciona el mejor motor según el perfil
# ══════════════════════════════════════════════════════════════

def buscar_ofertas_candidato(candidato) -> list:
    """
    Orquestador principal — selecciona el motor correcto según perfil.
    Implementa fallback en cascada si el motor principal falla.

    Motor 1 — SerpAPI:  inglés + remoto
    Motor 2 — Adzuna:   español + remoto
    Motor 3 — Jooble:   español + presencial o híbrido (toda Latam)

    Seguridad: nunca lanza excepción, siempre retorna lista.
    """
    from talent_app.models import IdiomaCandiato

    modalidad = candidato.modalidad

    # Detectar idioma
    idiomas_qs = IdiomaCandiato.objects.filter(candidato=candidato)
    idiomas_lista = [i.idioma.lower() for i in idiomas_qs]
    habla_ingles = any('ingl' in i for i in idiomas_lista)

    # Motor 1 — SerpAPI: inglés + remoto
    if habla_ingles and modalidad == 'remoto':
        _logger_ofertas.info(
            f'buscar_ofertas_candidato: candidato {candidato.pk} '
            f'→ Motor SerpAPI (inglés + remoto)'
        )
        ofertas = buscar_ofertas_serpapi(candidato)
        if not ofertas:
            _logger_ofertas.warning(
                f'buscar_ofertas_candidato: SerpAPI falló → fallback Adzuna'
            )
            ofertas = buscar_ofertas_adzuna(candidato)

    # Motor 2 — Adzuna: español + remoto
    elif modalidad == 'remoto':
        _logger_ofertas.info(
            f'buscar_ofertas_candidato: candidato {candidato.pk} '
            f'→ Motor Adzuna (español + remoto)'
        )
        ofertas = buscar_ofertas_adzuna(candidato)
        if not ofertas:
            _logger_ofertas.warning(
                f'buscar_ofertas_candidato: Adzuna falló → fallback SerpAPI'
            )
            ofertas = buscar_ofertas_serpapi(candidato)

    # Motor 3 — SerpAPI español: presencial/híbrido
    else:
        _logger_ofertas.info(
            f'buscar_ofertas_candidato: candidato {candidato.pk} '
            f'→ Motor SerpAPI español (presencial/híbrido)'
        )
        ofertas = buscar_ofertas_serpapi(candidato)
        if not ofertas:
            _logger_ofertas.warning(
                f'buscar_ofertas_candidato: SerpAPI falló → fallback Jooble'
            )
            ofertas = buscar_ofertas_jooble(candidato)

    return ofertas