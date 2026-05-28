import logging
from celery import shared_task
from .services import extraer_datos_cv

logger = logging.getLogger('talent_app')


@shared_task(bind=True)
def procesar_cv_task(self, contenido_bytes_hex):
    """
    Task de Celery para procesar CV con Gemini en segundo plano.
    Recibe el contenido del PDF como hex string para ser serializable.
    """
    try:
        contenido_bytes = bytes.fromhex(contenido_bytes_hex)
        datos = extraer_datos_cv(contenido_bytes)
        return {'ok': True, 'datos': datos}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
    acks_late=True,
)
def actualizar_embedding_task(self, candidato_id):
    """
    Genera y guarda el embedding vectorial de un candidato en segundo plano.

    Disparado desde editar_perfil después de guardar todo, para no bloquear
    la experiencia del usuario. Si Gemini falla, Celery reintenta hasta 3
    veces con backoff exponencial (8s, 16s, 32s...).

    Args:
        candidato_id: PK del candidato a procesar.

    Returns:
        dict con resultado para que Celery lo guarde como historial.
    """
    from .models import Candidato
    from .embeddings import actualizar_embedding_candidato

    try:
        candidato = Candidato.objects.get(pk=candidato_id)
    except Candidato.DoesNotExist:
        logger.warning(
            f'actualizar_embedding_task: candidato {candidato_id} no existe, '
            f'se omite (posiblemente eliminado)'
        )
        return {'ok': False, 'error': 'candidato no existe'}

    ok = actualizar_embedding_candidato(candidato)
    return {
        'ok': ok,
        'candidato_id': candidato_id,
        'candidato_nombre': candidato.nombre,
    }