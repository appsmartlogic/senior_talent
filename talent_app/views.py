from weakref import ref

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
import stripe
import json

import logging
from django.contrib.postgres.search import SearchVector

from urllib3 import request
logger = logging.getLogger('talent_app')


from .models import (
    Usuario, Pais, Sector, Candidato, ExperienciaLaboral,
    Educacion, IdiomaCandiato, Empresa, DescargaCV, EMAILS_BLOQUEADOS
)

stripe.api_key = settings.STRIPE_SECRET_KEY


# ──────────────────────────────────────────
# PÚBLICAS
# ──────────────────────────────────────────

def home(request):
    pais_codigo = request.pais_codigo
    total = Candidato.objects.filter(estado=Candidato.ESTADO_APROBADO).count()
    total_pais = Candidato.objects.filter(estado=Candidato.ESTADO_APROBADO, pais__codigo=pais_codigo).count()
    sectores = Sector.objects.all()
    return render(request, 'talent_app/home.html', {
        'total': total,
        'total_pais': total_pais,
        'sectores': sectores,
    })


def directorio(request):
    candidatos = Candidato.objects.filter(
        estado=Candidato.ESTADO_APROBADO
    ).select_related('pais').prefetch_related('sectores', 'idiomas')

    pais = request.GET.get('pais', request.pais_codigo)
    if pais and pais != 'todos':
        candidatos = candidatos.filter(pais__codigo=pais)

    sector = request.GET.get('sector')
    if sector:
        candidatos = candidatos.filter(sectores__slug=sector)

    exp_min = request.GET.get('exp_min')
    if exp_min:
        candidatos = candidatos.filter(años_experiencia__gte=int(exp_min))

    idioma = request.GET.get('idioma')
    if idioma:
        candidatos = candidatos.filter(idiomas__idioma__icontains=idioma)

    nivel_idioma = request.GET.get('nivel_idioma')
    if nivel_idioma:
        candidatos = candidatos.filter(idiomas__nivel=nivel_idioma)

    disponibilidad = request.GET.get('disponibilidad')
    if disponibilidad:
        candidatos = candidatos.filter(disponibilidad=disponibilidad)

    q = request.GET.get('q')
    if q:
        from functools import reduce
        import operator

        import unicodedata
        def normalizar(texto):
            return ''.join(
                c for c in unicodedata.normalize('NFD', texto.lower())
                if unicodedata.category(c) != 'Mn'
            )

        # DESPUÉS
        def filtro_termino(termino):
            return (
                Q(cargo_actual__unaccent__icontains=termino) |
                Q(habilidades__unaccent__icontains=termino) |
                Q(resumen__unaccent__icontains=termino) |
                Q(ciudad__unaccent__icontains=termino) |
                Q(pais__nombre__unaccent__icontains=termino) |
                Q(sectores__nombre__unaccent__icontains=termino) |
                Q(idiomas__idioma__unaccent__icontains=termino) |
                Q(disponibilidad__unaccent__icontains=termino)
            )

        # Frases separadas por coma = OR entre ellas
        # Palabras dentro de cada frase = AND entre ellas
        frases = [f.strip() for f in q.split(',') if f.strip()]
        query_total = None
        for frase in frases:
            palabras = [p.strip() for p in frase.split() if p.strip()]
            if not palabras:
                continue
            query_frase = reduce(operator.and_, [filtro_termino(p) for p in palabras])
            query_total = query_frase if query_total is None else (query_total | query_frase)

        if query_total is not None:
            candidatos = candidatos.filter(query_total).distinct()

    paises   = Pais.objects.filter(activo=True)
    sectores = Sector.objects.all()

    es_empresa_activa = (
        request.user.is_authenticated
        and hasattr(request.user, 'empresa')
        and request.user.empresa.estado == 'activa'
    )
    return render(request, 'talent_app/directorio.html', {
        'candidatos': candidatos.distinct(),
        'paises': paises,
        'sectores': sectores,
        'filtros': request.GET,
        'es_empresa_activa': es_empresa_activa,
    })

def perfil_candidato(request, pk):
    candidato = get_object_or_404(Candidato, pk=pk, estado=Candidato.ESTADO_APROBADO)
    ya_pago = False
    empresa_activa = False
    if request.user.is_authenticated and hasattr(request.user, 'empresa'):
        ya_pago = DescargaCV.objects.filter(
            empresa=request.user.empresa,
            candidato=candidato,
            estado=DescargaCV.ESTADO_PAGADO
        ).exists()
        empresa_activa = request.user.empresa.activa
    return render(request, 'talent_app/perfil_candidato.html', {
        'candidato': candidato,
        'ya_pago': ya_pago,
        'empresa_activa': empresa_activa,
    })

# ──────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────

def registro_candidato(request):
    paises = Pais.objects.filter(activo=True)
    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        nombre   = request.POST.get('nombre', '').strip()
        pais_id  = request.POST.get('pais')
        ciudad   = request.POST.get('ciudad', '').strip()

        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Ya existe una cuenta con ese correo.')
            return render(request, 'talent_app/registro_candidato.html', {'paises': paises})

        usuario = Usuario.objects.create_user(email=email, password=password, tipo=Usuario.TIPO_CANDIDATO)
        Candidato.objects.create(
            usuario=usuario,
            nombre=nombre,
            pais_id=pais_id,
            ciudad=ciudad,
            cargo_actual='',
            años_experiencia=0,
        )
        login(request, usuario)
        messages.success(request, '¡Cuenta creada! Completa tu perfil y sube tu CV.')
        return redirect('editar_perfil')

    return render(request, 'talent_app/registro_candidato.html', {'paises': paises})


def registro_empresa(request):
    paises = Pais.objects.filter(activo=True)
    if request.method == 'POST':
        email          = request.POST.get('email', '').strip().lower()
        password       = request.POST.get('password', '')
        nombre         = request.POST.get('nombre', '').strip()
        pais_id        = request.POST.get('pais')
        num_tributario = request.POST.get('num_tributario', '').strip()

        dominio = email.split('@')[-1] if '@' in email else ''
        if dominio in EMAILS_BLOQUEADOS:
            messages.error(request, 'Debes usar un correo corporativo (no Gmail, Hotmail, etc.).')
            return render(request, 'talent_app/registro_empresa.html', {'paises': paises})

        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Ya existe una cuenta con ese correo.')
            return render(request, 'talent_app/registro_empresa.html', {'paises': paises})

        usuario = Usuario.objects.create_user(email=email, password=password, tipo=Usuario.TIPO_EMPRESA)
        Empresa.objects.create(
            usuario=usuario,
            nombre=nombre,
            pais_id=pais_id,
            num_tributario=num_tributario,
        )
        login(request, usuario)
        messages.success(request, '¡Empresa registrada! Tu cuenta será verificada pronto.')
        return redirect('empresa_candidatos')

    return render(request, 'talent_app/registro_empresa.html', {'paises': paises})


def login_view(request):
    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        usuario  = authenticate(request, email=email, password=password)
        if usuario:
            login(request, usuario)
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        messages.error(request, 'Correo o contraseña incorrectos.')
    return render(request, 'talent_app/login.html')


def logout_view(request):
    logout(request)
    return redirect('home')


# ──────────────────────────────────────────
# DASHBOARD CANDIDATO
# ──────────────────────────────────────────

@login_required
def dashboard(request):
    if hasattr(request.user, 'empresa'):
        return redirect('empresa_candidatos')
    candidato = get_object_or_404(Candidato, usuario=request.user)
    descargas = DescargaCV.objects.filter(
        candidato=candidato,
        estado=DescargaCV.ESTADO_PAGADO
    ).count()
    return render(request, 'talent_app/dashboard_candidato.html', {
        'candidato': candidato,
        'total_descargas': descargas,
    })


@login_required
def editar_perfil(request):
    candidato = get_object_or_404(Candidato, usuario=request.user)
    sectores  = Sector.objects.all()
    paises    = Pais.objects.filter(activo=True)

    if request.method == 'POST':
        candidato.nombre          = request.POST.get('nombre', candidato.nombre).strip()
        candidato.ciudad          = request.POST.get('ciudad', candidato.ciudad).strip()
        candidato.cargo_actual    = request.POST.get('cargo_actual', '').strip()
        candidato.años_experiencia = int(request.POST.get('años_experiencia', 0))
        candidato.resumen         = request.POST.get('resumen', '').strip()
        candidato.disponibilidad  = request.POST.get('disponibilidad', Candidato.DISPONIBILIDAD_INMEDIATA)
        candidato.modalidad       = request.POST.get('modalidad', Candidato.MODALIDAD_HIBRIDO)

        habilidades_raw = request.POST.get('habilidades', '')
        candidato.habilidades = [h.strip() for h in habilidades_raw.split(',') if h.strip()]

        if 'foto' in request.FILES:
            candidato.foto = request.FILES['foto']

        sectores_ids = request.POST.getlist('sectores')
        candidato.sectores.set(sectores_ids)

        if candidato.años_experiencia < 5:
            messages.error(request, 'La plataforma es exclusiva para profesionales con 10+ años de experiencia.')
            return render(request, 'talent_app/editar_perfil.html', {
                'candidato': candidato,
                'sectores': sectores,
                'paises': paises
            })

        candidato.save()

        # Guardar experiencias
        candidato.experiencias.all().delete()
        empresas = request.POST.getlist('exp_empresa')
        cargos   = request.POST.getlist('exp_cargo')
        inicios  = request.POST.getlist('exp_inicio')
        fines    = request.POST.getlist('exp_fin')
        descs    = request.POST.getlist('exp_desc')
        for i, empresa in enumerate(empresas):
            if empresa.strip():
                ExperienciaLaboral.objects.create(
                    candidato=candidato,
                    empresa=empresa.strip(),
                    cargo=cargos[i].strip() if i < len(cargos) else '',
                    año_inicio=int(inicios[i]) if i < len(inicios) and inicios[i] else 0,
                    año_fin=int(fines[i]) if i < len(fines) and fines[i] else None,
                    descripcion=descs[i].strip() if i < len(descs) else '',
                    orden=i,
                )

        # Guardar educación
        candidato.educaciones.all().delete()
        titulos       = request.POST.getlist('edu_titulo')
        instituciones = request.POST.getlist('edu_institucion')
        anos_edu      = request.POST.getlist('edu_año')
        for i, titulo in enumerate(titulos):
            if titulo.strip():
                Educacion.objects.create(
                    candidato=candidato,
                    titulo=titulo.strip(),
                    institucion=instituciones[i].strip() if i < len(instituciones) else '',
                    año_fin=int(anos_edu[i]) if i < len(anos_edu) and anos_edu[i] else None,
                    orden=i,
                )

        # Guardar idiomas
        candidato.idiomas.all().delete()
        idiomas_nombres = request.POST.getlist('idioma_nombre')
        idiomas_niveles = request.POST.getlist('idioma_nivel')
        for i, idioma in enumerate(idiomas_nombres):
            if idioma.strip():
                IdiomaCandiato.objects.create(
                    candidato=candidato,
                    idioma=idioma.strip(),
                    nivel=idiomas_niveles[i] if i < len(idiomas_niveles) else 'intermedio',
                )

        messages.success(request, 'Perfil actualizado correctamente.')
        return redirect('dashboard')

    return render(request, 'talent_app/editar_perfil.html', {
        'candidato': candidato,
        'sectores': sectores,
        'paises': paises,
    })


@login_required
@require_POST
def subir_cv_ia(request):
    """
    Recibe el PDF, lanza task de Celery y devuelve task_id inmediatamente.
    El archivo NUNCA se guarda en disco.
    """
    archivo = request.FILES.get('cv')
    if not archivo:
        return JsonResponse({'error': 'No se recibió archivo'}, status=400)

    if not archivo.name.lower().endswith('.pdf'):
        return JsonResponse({'error': 'Solo se aceptan archivos PDF'}, status=400)

    if archivo.size > 10 * 1024 * 1024:
        return JsonResponse({'error': 'El archivo supera el límite de 10 MB'}, status=400)

    try:
        from .tasks import procesar_cv_task
        contenido_bytes = archivo.read()
        del archivo
        # Convertir a hex para que Celery pueda serializarlo
        contenido_hex = contenido_bytes.hex()
        task = procesar_cv_task.delay(contenido_hex)
        return JsonResponse({'ok': True, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def estado_tarea(request, task_id):
    """
    Polling — el frontend consulta cada 3 segundos el estado de la tarea.
    """
    from celery.result import AsyncResult
    result = AsyncResult(task_id)

    if result.state == 'PENDING':
        return JsonResponse({'estado': 'pendiente'})
    elif result.state == 'SUCCESS':
        return JsonResponse({'estado': 'listo', 'resultado': result.result})
    elif result.state == 'FAILURE':
        return JsonResponse({'estado': 'error', 'error': str(result.result)})
    else:
        return JsonResponse({'estado': result.state.lower()})
# ──────────────────────────────────────────
# DASHBOARD EMPRESA
# ──────────────────────────────────────────
@login_required
def empresa_candidatos(request):
    empresa = get_object_or_404(Empresa, usuario=request.user)
    descargas_pagadas = DescargaCV.objects.filter(
        empresa=empresa,
        estado=DescargaCV.ESTADO_PAGADO
    ).select_related('candidato', 'candidato__pais').order_by('-pagado_en')

    total_invertido = sum(d.monto_usd for d in descargas_pagadas if d.monto_usd)

    return render(request, 'talent_app/empresa_candidatos.html', {
        'empresa': empresa,
        'descargas': descargas_pagadas,
        'total_invertido': total_invertido,
    })


def pago_exito(request):
    session_id = request.GET.get('session_id')
    descarga = None
    if session_id:
        descarga = DescargaCV.objects.filter(
            stripe_session_id=session_id,
            estado=DescargaCV.ESTADO_PAGADO
        ).select_related('candidato').first()
    return render(request, 'talent_app/pago_exito.html', {'descarga': descarga})


def pago_cancelado(request):
    return render(request, 'talent_app/pago_cancelado.html')


# ──────────────────────────────────────────
# STRIPE WEBHOOK
# ──────────────────────────────────────────

@csrf_exempt
def stripe_webhook(request):
    payload    = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        session     = event['data']['object']
        meta        = session.get('metadata', {})
        descarga_id = meta.get('descarga_id')

        if descarga_id:
            try:
                descarga = DescargaCV.objects.get(pk=descarga_id)
                descarga.estado            = DescargaCV.ESTADO_PAGADO
                descarga.stripe_payment_id = session.get('payment_intent', '')
                import pytz
                zona = pytz.timezone(descarga.empresa.pais.zona_horaria)
                descarga.pagado_en = timezone.now().astimezone(zona)
                descarga.monto_usd = transaction.get('amount_in_cents', 0) / 100
                descarga.save(update_fields=['estado', 'stripe_payment_id', 'pagado_en', 'monto_usd'])
                 # Enviar emails a candidato y empresa
                from .emails import enviar_email_descarga_cv
                enviar_email_descarga_cv(descarga.empresa, descarga.candidato)

            except DescargaCV.DoesNotExist:
                pass

    return HttpResponse(status=200)


@login_required
def descargar_pdf_cv(request, candidato_id):
    empresa   = get_object_or_404(Empresa, usuario=request.user)
    candidato = get_object_or_404(Candidato, pk=candidato_id)

    # Verificar que la empresa pagó este CV
    descarga = get_object_or_404(
        DescargaCV,
        empresa=empresa,
        candidato=candidato,
        estado=DescargaCV.ESTADO_PAGADO
    )

    # Generar PDF con WeasyPrint
    from django.template.loader import render_to_string
    from weasyprint import HTML
    import tempfile
    import os

    html_string = render_to_string('talent_app/cv_pdf.html', {
        'candidato': candidato,
    })

    # Generar PDF en memoria
    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    nombre_archivo = f"CV_{candidato.nombre.replace(' ', '_')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


def error_403(request, exception=None):
    return render(request, '403.html', status=403)

@login_required
def iniciar_pago(request, candidato_id):
    empresa   = get_object_or_404(Empresa, usuario=request.user)
    candidato = get_object_or_404(Candidato, pk=candidato_id, estado=Candidato.ESTADO_APROBADO)

    logger.info(f'Empresa {empresa.nombre} intenta descargar CV de {candidato.nombre}')

    ya_pago = DescargaCV.objects.filter(
        empresa=empresa,
        candidato=candidato,
        estado=DescargaCV.ESTADO_PAGADO
    ).exists()
    if ya_pago:
        logger.info(f'CV ya descargado previamente — empresa: {empresa.nombre}')
        messages.info(request, 'Ya descargaste este CV anteriormente.')
        return redirect('empresa_candidatos')

    # Obtener pasarela configurada para el país de la empresa
    try:
        pasarela_config = empresa.pais.pasarela
        if not pasarela_config.activa:
            messages.error(request, 'No hay pasarela de pago activa para tu país. Contáctanos.')
            return redirect('perfil_candidato', pk=candidato_id)
    except Exception:
        messages.error(request, 'No hay pasarela de pago configurada para tu país. Contáctanos.')
        logger.error(f'Sin pasarela configurada para país: {empresa.pais.nombre}')
        return redirect('perfil_candidato', pk=candidato_id)

    try:
        descarga, _ = DescargaCV.objects.get_or_create(
            empresa=empresa,
            candidato=candidato,
            defaults={'estado': DescargaCV.ESTADO_PENDIENTE}
        )

        pasarela = pasarela_config.pasarela

        if pasarela == 'stripe':
            import stripe as stripe_lib
            stripe_lib.api_key = pasarela_config.secret_key
            session = stripe_lib.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': pasarela_config.moneda.lower(),
                        'product_data': {'name': f'CV — {candidato.nombre}'},
                        'unit_amount': pasarela_config.precio_cv * 100,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=request.build_absolute_uri(f'/pago/exito/?session_id={{CHECKOUT_SESSION_ID}}'),
                cancel_url=request.build_absolute_uri('/pago/cancelado/'),
                metadata={
                    'descarga_id': descarga.pk,
                    'empresa_id':  empresa.pk,
                    'candidato_id': candidato.pk,
                    'pasarela': pasarela,
                }
            )
            descarga.stripe_session_id = session.id
            descarga.save(update_fields=['stripe_session_id'])
            logger.info(f'Sesión Stripe creada: {session.id} — empresa: {empresa.nombre}')
            return redirect(session.url, code=303)

        elif pasarela == 'wompi':
            # Wompi — Colombia
            # Redirige al checkout de Wompi
            import hashlib
            import time
            ref = f'ST-{descarga.pk}-{int(time.time())}'
            descarga.stripe_session_id = ref
            descarga.save(update_fields=['stripe_session_id'])

            monto_centavos = pasarela_config.precio_cv * 100
            integrity_string = f"{ref}{monto_centavos}{pasarela_config.moneda.upper()}{pasarela_config.webhook_secret}"
            signature = hashlib.sha256(integrity_string.encode('utf-8')).hexdigest()

            wompi_url = (
                f"https://checkout.wompi.co/p/"
                f"?public-key={pasarela_config.public_key}"
                f"&currency={pasarela_config.moneda.upper()}"
                f"&amount-in-cents={monto_centavos}"
                f"&reference={ref}"
                f"&signature:integrity={signature}"
                f"&redirect-url={request.build_absolute_uri('/pago/exito/')}"
            )

            logger.info(f'Wompi — ref: {ref} | monto: {pasarela_config.precio_cv} | moneda: {pasarela_config.moneda}')
            logger.info(f'Wompi — integrity_string: {ref}{pasarela_config.precio_cv}{pasarela_config.moneda}{pasarela_config.webhook_secret}')

            logger.info(f'Checkout Wompi iniciado — empresa: {empresa.nombre} — ref: {ref}')
            return redirect(wompi_url)

        elif pasarela == 'mercadopago':
            import mercadopago
            sdk = mercadopago.SDK(pasarela_config.secret_key)
            preference = sdk.preference().create({
                "items": [{
                    "title": f"CV — {candidato.nombre}",
                    "quantity": 1,
                    "unit_price": pasarela_config.precio_cv,
                    "currency_id": pasarela_config.moneda,
                }],
                "back_urls": {
                    "success": request.build_absolute_uri('/pago/exito/'),
                    "failure": request.build_absolute_uri('/pago/cancelado/'),
                },
                "auto_return": "approved",
                "external_reference": str(descarga.pk),
            })
            logger.info(f'Preferencia MercadoPago creada — empresa: {empresa.nombre}')
            return redirect(preference["response"]["init_point"])

        else:
            messages.error(request, f'Pasarela {pasarela} no implementada aún.')
            return redirect('perfil_candidato', pk=candidato_id)

    except Exception as e:
        logger.error(f'Error al procesar pago — empresa: {empresa.nombre} — error: {e}')
        messages.error(request, 'Error al procesar el pago. Intenta de nuevo.')
        return redirect('perfil_candidato', pk=candidato_id)
    

@csrf_exempt
def wompi_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        payload = json.loads(request.body)
        logger.info(f'Wompi webhook recibido: {json.dumps(payload)}')

        evento = payload.get('event')
        if evento != 'transaction.updated':
            return HttpResponse(status=200)

        data        = payload.get('data', {})
        transaction = data.get('transaction', {})
        estado      = transaction.get('status')
        referencia  = transaction.get('reference', '')

        logger.info(f'Wompi — transacción: {referencia} | estado: {estado}')

        # Si la referencia es de SmartLogicApp reenviar
        if not referencia.startswith('ST-'):
            import requests as req_lib
            try:
                resp = req_lib.post(
                    'https://smartlogicapp.com/directorio/api/wompi/webhook/',
                    json=payload,
                    timeout=10,
                    headers={'Content-Type': 'application/json'}
                )
                logger.info(f'Webhook reenviado a SmartLogicApp — status: {resp.status_code}')
            except Exception as e:
                logger.error(f'Error reenviando a SmartLogicApp: {e}')
            return HttpResponse(status=200)

        # Procesar pagos de SeniorTalent
        if estado == 'APPROVED' and referencia.startswith('ST-'):
            try:
                partes      = referencia.split('-')
                descarga_id = partes[1]
                descarga    = DescargaCV.objects.get(pk=descarga_id)

                if descarga.estado != DescargaCV.ESTADO_PAGADO:
                    descarga.estado            = DescargaCV.ESTADO_PAGADO
                    descarga.stripe_payment_id = transaction.get('id', '')
                    import pytz
                    zona = pytz.timezone(descarga.empresa.pais.zona_horaria)
                    descarga.pagado_en = timezone.now().astimezone(zona)
                    descarga.monto_usd = transaction.get('amount_in_cents', 0) / 100
                    descarga.save(update_fields=['estado', 'stripe_payment_id', 'pagado_en', 'monto_usd'])
                    from .emails import enviar_email_descarga_cv
                    enviar_email_descarga_cv(descarga.empresa, descarga.candidato)
                    logger.info(f'Wompi — descarga {descarga_id} marcada como pagada')

            except DescargaCV.DoesNotExist:
                logger.error(f'Wompi webhook — descarga no encontrada: {referencia}')

        return HttpResponse(status=200)

    except Exception as e:
        logger.error(f'Wompi webhook error: {e}')
        return HttpResponse(status=200)

    
def error_404(request, exception=None):
    return render(request, '404.html', status=404)


@login_required
def solicitar_soporte(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    empresa = get_object_or_404(Empresa, usuario=request.user)
    asunto  = request.POST.get('asunto', '').strip()
    mensaje = request.POST.get('mensaje', '').strip()
    archivo = request.FILES.get('archivo')

    if not asunto or not mensaje:
        return JsonResponse({'ok': False, 'error': 'Faltan campos'}, status=400)

    try:
        from django.core.mail import EmailMessage
        cuerpo = f"""Solicitud de soporte desde SeniorTalent

Empresa : {empresa.nombre}
País    : {empresa.pais.nombre}
Email   : {empresa.usuario.email}
Estado  : {empresa.estado}

Asunto: {asunto}

Mensaje:
{mensaje}
"""
        email = EmailMessage(
            subject=f'[SeniorTalent Soporte] {asunto}',
            body=cuerpo,
            from_email='no-reply@smartlogicapp.com',
            to=['info@smartlogicapp.com'],
            reply_to=[empresa.usuario.email],
        )
        if archivo:
            email.attach(archivo.name, archivo.read(), archivo.content_type)

        email.send()
        logger.info(f'Soporte enviado — empresa: {empresa.nombre} — asunto: {asunto}')
        return JsonResponse({'ok': True})

    except Exception as e:
        logger.error(f'Error enviando soporte: {e}')
        return JsonResponse({'ok': False}, status=500)
    