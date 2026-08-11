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


@shared_task(
    bind=True,
    max_retries=0,
    time_limit=180,
    soft_time_limit=150,
)
def enviar_ofertas_laborales_task(self):
    """
    Tarea nocturna (lunes a viernes, 11pm Bogotá).
    Selecciona 4 candidatos aprobados que llevan más tiempo
    sin recibir email de ofertas y les envía 3 ofertas reales
    buscadas en SerpAPI y rankeadas por Gemini según su perfil y país.
    Función nueva — no modifica nada existente.
    Solo escribe en el campo ultima_oferta_enviada.
    """
    import logging
    from django.utils import timezone
    from .models import Candidato
    from .services import buscar_ofertas_serpapi, rankear_ofertas_gemini
    from .emails import enviar_email_ofertas_laborales

    logger = logging.getLogger('talent_app')
    hoy = timezone.now().date()

    # Seleccionar 4 candidatos aprobados:
    # NULL primero (nunca han recibido),
    # luego los que llevan más días sin recibir.
    candidatos = (
        Candidato.objects
        .filter(estado=Candidato.ESTADO_APROBADO)
        .select_related('usuario', 'pais')
        .prefetch_related('sectores')
        .order_by('ultima_oferta_enviada')
        [:4]
    )

    if not candidatos:
        logger.info('enviar_ofertas_laborales_task: no hay candidatos aprobados')
        return {'ok': True, 'enviados': 0}

    enviados = 0
    errores  = 0

    for candidato in candidatos:
        try:
            logger.info(
                f'enviar_ofertas_laborales_task: procesando '
                f'{candidato.pk} — {candidato.nombre}'
            )

            # 1. Buscar ofertas reales en SerpAPI según país y perfil
            ofertas_raw = buscar_ofertas_serpapi(candidato)
            if not ofertas_raw:
                logger.warning(
                    f'enviar_ofertas_laborales_task: sin resultados SerpAPI '
                    f'para candidato {candidato.pk}'
                )
                # Marcar igual para rotar al siguiente candidato mañana
                candidato.ultima_oferta_enviada = hoy
                candidato.save(update_fields=['ultima_oferta_enviada'])
                continue

            # 2. Rankear con Gemini → top 3
            ofertas_top = rankear_ofertas_gemini(candidato, ofertas_raw)
            if not ofertas_top:
                logger.warning(
                    f'enviar_ofertas_laborales_task: Gemini no seleccionó '
                    f'ofertas para candidato {candidato.pk}'
                )
                candidato.ultima_oferta_enviada = hoy
                candidato.save(update_fields=['ultima_oferta_enviada'])
                continue

            # 3. Enviar email
            enviar_email_ofertas_laborales(candidato, ofertas_top)

            # 4. Marcar fecha de último envío
            candidato.ultima_oferta_enviada = hoy
            candidato.save(update_fields=['ultima_oferta_enviada'])

            enviados += 1
            logger.info(
                f'enviar_ofertas_laborales_task: email enviado a '
                f'{candidato.nombre} con {len(ofertas_top)} ofertas'
            )

        except Exception as e:
            errores += 1
            logger.error(
                f'enviar_ofertas_laborales_task: error en candidato '
                f'{candidato.pk} → {e}'
            )
            continue

    logger.info(
        f'enviar_ofertas_laborales_task: finalizada — '
        f'enviados={enviados} errores={errores}'
    )
    return {'ok': True, 'enviados': enviados, 'errores': errores}