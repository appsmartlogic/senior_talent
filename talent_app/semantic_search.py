import hashlib
import logging
from django.core.cache import cache
from pgvector.django import CosineDistance
from .embeddings import generar_embedding

logger = logging.getLogger('talent_app')

CACHE_TTL = 60 * 60
CACHE_PREFIX = 'semantic_query_v1'


def _cache_key(frase):
    h = hashlib.md5(frase.lower().strip().encode('utf-8')).hexdigest()
    return f'{CACHE_PREFIX}:{h}'


def embedding_de_consulta(frase):
    if not frase or not frase.strip():
        return None

    frase_limpia = frase.strip().lower()[:500]
    key = _cache_key(frase_limpia)

    try:
        cacheado = cache.get(key)
        if cacheado is not None:
            logger.info(f'embedding_de_consulta: cache HIT para "{frase_limpia[:50]}..."')
            return cacheado
    except Exception as e:
        logger.warning(f'embedding_de_consulta: cache no disponible ({e})')

    resultado = generar_embedding(frase_limpia, task_type='RETRIEVAL_QUERY')
    if resultado is None:
        return None

    vector, _modelo = resultado

    try:
        cache.set(key, vector, CACHE_TTL)
        logger.info(f'embedding_de_consulta: cache SET para "{frase_limpia[:50]}..." (TTL {CACHE_TTL}s)')
    except Exception as e:
        logger.warning(f'embedding_de_consulta: no se pudo cachear ({e})')

    return vector


def buscar_candidatos_semantico(frase, queryset_base, limite=10, umbral_distancia=0.33):
    try:
        vector = embedding_de_consulta(frase)
        if vector is None:
            logger.warning(f'buscar_candidatos_semantico: sin embedding para "{frase[:50]}", se omite')
            return None

        queryset_filtrado = queryset_base.exclude(embedding__isnull=True)

        resultados = (
            queryset_filtrado
            .annotate(distancia=CosineDistance('embedding', vector))
            .filter(distancia__lte=umbral_distancia)
            .order_by('distancia')[:limite]
        )

        logger.info(
            f'buscar_candidatos_semantico: "{frase[:50]}" '
            f'-> umbral={umbral_distancia}'
        )

        return resultados

    except Exception as e:
        logger.error(f'buscar_candidatos_semantico: error -> {e}')
        return None

def es_consulta_semantica(frase):
    """
    Decide si una frase amerita búsqueda semántica o si la fulltext basta.

    Regla simple y universal:
    - Coma en la frase → fulltext (el usuario eligió modo OR explícito)
    - 1 a 3 palabras → fulltext (búsqueda por keyword, más precisa)
    - 4 o más palabras → semántica (probablemente lenguaje natural)

    Sin lista de palabras quemadas — funciona para cualquier expresión.
    """
    if not frase or not frase.strip():
        return False

    frase = frase.strip().lower()

    if ',' in frase:
        return False

    palabras = [p for p in frase.split() if len(p) >= 2]

    return len(palabras) >= 4