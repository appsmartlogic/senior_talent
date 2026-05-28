"""
Servicio de embeddings vectoriales — fase 3.

Convierte texto en vectores de 768 dimensiones usando Gemini.
Los vectores se guardan en el campo Candidato.embedding (tipo pgvector).

Filosofía:
- Funciones puras con try/except defensivo
- Fallback entre modelos por si Google retira uno
- Logging detallado para auditoría de costos
- NUNCA propaga excepciones al flujo del candidato:
  si falla la generación del embedding, el perfil se guarda igual
  y el embedding queda con su valor anterior (o NULL si era nuevo)

Costo: ~$0.00003 USD por embedding (≈ 200 tokens promedio).
"""
import logging
import requests
from datetime import datetime
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('talent_app')

import os
MODELOS_EMBEDDING = [
    os.getenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001'),
]

EMBEDDING_DIMENSIONES = 768
EMBEDDING_TIMEOUT = 30  # segundos


def generar_embedding(texto, task_type='RETRIEVAL_DOCUMENT'):
    """
    Convierte texto en un vector de 768 dimensiones usando Gemini.

    Args:
        texto: string con el contenido a vectorizar.
        task_type: 'RETRIEVAL_DOCUMENT' para perfiles guardados,
                   'RETRIEVAL_QUERY' para frases de búsqueda.
                   Esta distinción la pide Gemini para mejor calidad.

    Returns:
        - Lista de 768 floats si tuvo éxito.
        - None si falló (loguea el error pero no lo lanza).
    """
    if not texto or not texto.strip():
        logger.warning('generar_embedding: texto vacío, se devuelve None')
        return None

    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        logger.error('generar_embedding: GEMINI_API_KEY no configurada')
        return None

    # Limitar el tamaño del texto enviado a Gemini.
    # Un perfil típico tiene ~800 chars; cortamos defensivamente a 8000
    # para no superar el límite de tokens por llamada ni inflar el costo.
    texto = texto.strip()[:8000]

    payload = {
        'content': {'parts': [{'text': texto}]},
        'outputDimensionality': EMBEDDING_DIMENSIONES,
        'taskType': task_type,
    }

    ultimo_error = None

    for modelo in MODELOS_EMBEDDING:
        url = (
            f'https://generativelanguage.googleapis.com/v1beta/models/'
            f'{modelo}:embedContent?key={api_key}'
        )
        try:
            payload_completo = {**payload, 'model': f'models/{modelo}'}
            resp = requests.post(url, json=payload_completo, timeout=EMBEDDING_TIMEOUT)

            if not resp.ok:
                ultimo_error = f'{modelo} → HTTP {resp.status_code}: {resp.text[:200]}'
                logger.warning(f'generar_embedding: {ultimo_error}')
                continue

            data = resp.json()
            valores = data.get('embedding', {}).get('values', [])

            if len(valores) != EMBEDDING_DIMENSIONES:
                ultimo_error = (
                    f'{modelo} → respuesta con {len(valores)} dimensiones, '
                    f'esperaba {EMBEDDING_DIMENSIONES}'
                )
                logger.warning(f'generar_embedding: {ultimo_error}')
                continue

            logger.info(
                f'generar_embedding OK | modelo: {modelo} | '
                f'chars: {len(texto)} | dims: {len(valores)}'
            )
            return valores, modelo

        except requests.RequestException as e:
            ultimo_error = f'{modelo} → excepción: {e}'
            logger.warning(f'generar_embedding: {ultimo_error}')
            continue
        except Exception as e:
            ultimo_error = f'{modelo} → error inesperado: {e}'
            logger.error(f'generar_embedding: {ultimo_error}')
            continue

    logger.error(f'generar_embedding: todos los modelos fallaron. Último: {ultimo_error}')
    return None


def actualizar_embedding_candidato(candidato):
    """
    Genera y guarda el embedding para un Candidato.

    Usa el campo texto_busqueda (ya construido por search.py) como entrada.
    Si texto_busqueda está vacío, no hace nada (evita gastar llamada en vano).

    Returns:
        True  si se generó y guardó correctamente.
        False si no se pudo generar (sin tirar excepción).
    """
    try:
        if not candidato.texto_busqueda:
            logger.warning(
                f'actualizar_embedding_candidato: candidato {candidato.pk} '
                f'sin texto_busqueda, se omite'
            )
            return False

        resultado = generar_embedding(
            candidato.texto_busqueda,
            task_type='RETRIEVAL_DOCUMENT'
        )

        if resultado is None:
            return False

        vector, modelo_usado = resultado

        candidato.embedding = vector
        candidato.embedding_modelo = modelo_usado
        candidato.embedding_actualizado_en = timezone.now()
        candidato.save(update_fields=[
            'embedding',
            'embedding_modelo',
            'embedding_actualizado_en',
        ])

        logger.info(
            f'Embedding actualizado | candidato: {candidato.pk} '
            f'({candidato.nombre}) | modelo: {modelo_usado}'
        )
        return True

    except Exception as e:
        logger.error(
            f'actualizar_embedding_candidato: candidato {candidato.pk} → {e}'
        )
        return False