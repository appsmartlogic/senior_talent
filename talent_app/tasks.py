from celery import shared_task
from .services import extraer_datos_cv


@shared_task(bind=True)
def procesar_cv_task(self, contenido_bytes_hex):
    """
    Task de Celery para procesar CV con Ollama en segundo plano.
    Recibe el contenido del PDF como hex string para ser serializable.
    """
    try:
        contenido_bytes = bytes.fromhex(contenido_bytes_hex)
        datos = extraer_datos_cv(contenido_bytes)
        return {'ok': True, 'datos': datos}
    except Exception as e:
        return {'ok': False, 'error': str(e)}