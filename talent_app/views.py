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
        candidatos = candidatos.filter(
            Q(nombre__icontains=q) |
            Q(cargo_actual__icontains=q) |
            Q(habilidades__icontains=q)
        )

    paises   = Pais.objects.filter(activo=True)
    sectores = Sector.objects.all()

    return render(request, 'talent_app/directorio.html', {
        'candidatos': candidatos.distinct(),
        'paises': paises,
        'sectores': sectores,
        'filtros': request.GET,
    })


def perfil_candidato(request, pk):
    candidato = get_object_or_404(Candidato, pk=pk, estado=Candidato.ESTADO_APROBADO)
    ya_pago = False
    if request.user.is_authenticated and hasattr(request.user, 'empresa'):
        ya_pago = DescargaCV.objects.filter(
            empresa=request.user.empresa,
            candidato=candidato,
            estado=DescargaCV.ESTADO_PAGADO
        ).exists()
    return render(request, 'talent_app/perfil_candidato.html', {
        'candidato': candidato,
        'ya_pago': ya_pago,
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

    return render(request, 'talent_app/empresa_candidatos.html', {
        'empresa': empresa,
        'descargas': descargas_pagadas,
    })


@login_required
def iniciar_pago(request, candidato_id):
    empresa   = get_object_or_404(Empresa, usuario=request.user)
    candidato = get_object_or_404(Candidato, pk=candidato_id, estado=Candidato.ESTADO_APROBADO)

    ya_pago = DescargaCV.objects.filter(
        empresa=empresa,
        candidato=candidato,
        estado=DescargaCV.ESTADO_PAGADO
    ).exists()
    if ya_pago:
        messages.info(request, 'Ya descargaste este CV anteriormente.')
        return redirect('empresa_candidatos')

    descarga, _ = DescargaCV.objects.get_or_create(
        empresa=empresa,
        candidato=candidato,
        defaults={'estado': DescargaCV.ESTADO_PENDIENTE}
    )

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': f'CV — {candidato.nombre}'},
                'unit_amount': settings.PRECIO_CV_USD,
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=request.build_absolute_uri(f'/pago/exito/?session_id={{CHECKOUT_SESSION_ID}}'),
        cancel_url=request.build_absolute_uri('/pago/cancelado/'),
        metadata={
            'descarga_id': descarga.pk,
            'empresa_id': empresa.pk,
            'candidato_id': candidato.pk,
        }
    )
    descarga.stripe_session_id = session.id
    descarga.save(update_fields=['stripe_session_id'])
    return redirect(session.url, code=303)


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
                descarga.pagado_en         = timezone.now()
                descarga.save(update_fields=['estado', 'stripe_payment_id', 'pagado_en'])

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