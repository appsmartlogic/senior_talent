from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings


def enviar_email_descarga_cv(empresa, candidato):
    """
    Envía email al candidato notificando que una empresa descargó su CV.
    Envía email a la empresa confirmando la descarga con datos de contacto.
    """
    # ── Email al CANDIDATO ──────────────────────────
    asunto_candidato = f'Tu perfil fue descargado por {empresa.nombre}'
    html_candidato = render_to_string('talent_app/emails/notificacion_candidato.html', {
        'candidato': candidato,
        'empresa': empresa,
    })
    msg_candidato = EmailMultiAlternatives(
        subject=asunto_candidato,
        body=f'Tu perfil fue descargado por {empresa.nombre} en SeniorTalent.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[candidato.usuario.email],
    )
    msg_candidato.attach_alternative(html_candidato, 'text/html')
    msg_candidato.send(fail_silently=True)

    # ── Email a la EMPRESA ──────────────────────────
    asunto_empresa = f'CV descargado — {candidato.nombre}'
    html_empresa = render_to_string('talent_app/emails/confirmacion_empresa.html', {
        'candidato': candidato,
        'empresa': empresa,
    })
    msg_empresa = EmailMultiAlternatives(
        subject=asunto_empresa,
        body=f'Has descargado el CV de {candidato.nombre} en SeniorTalent.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[empresa.usuario.email],
    )
    msg_empresa.attach_alternative(html_empresa, 'text/html')
    msg_empresa.send(fail_silently=True)


def enviar_email_empresa_activa(empresa):
    """
    Notifica a la empresa cuando su cuenta es activada.
    """
    asunto = '¡Tu cuenta en SeniorTalent está activa!'
    html = render_to_string('talent_app/emails/empresa_activa.html', {
        'empresa': empresa,
    })
    msg = EmailMultiAlternatives(
        subject=asunto,
        body=f'Hola {empresa.nombre}, tu cuenta en Smart Logic App - SeniorTalent ha sido activada.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[empresa.usuario.email],
    )
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=True)