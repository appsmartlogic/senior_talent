from weakref import ref

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
import stripe
import json
import json as _json
import logging
from django.contrib.postgres.search import SearchVector

from urllib3 import request
logger = logging.getLogger('talent_app')


from .models import (
    Usuario, Pais, Sector, Candidato, ExperienciaLaboral,
    Educacion, IdiomaCandiato, Empresa, DescargaCV, EMAILS_BLOQUEADOS
)
from .search import actualizar_texto_busqueda
stripe.api_key = settings.STRIPE_SECRET_KEY


# ──────────────────────────────────────────
# RECUPERACIÓN DE CONTRASEÑA PERSONALIZADA
# ──────────────────────────────────────────
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from django.core.mail import send_mail as _send_mail

def password_reset_view(request):
    """Paso 1 — El usuario ingresa su email."""
    from django.contrib.auth.forms import PasswordResetForm
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        usuarios = Usuario.objects.filter(email=email, is_active=True)
        if usuarios.exists():
            for usuario in usuarios:
                uid = urlsafe_base64_encode(force_bytes(usuario.pk))
                token = default_token_generator.make_token(usuario)
                ctx = {
                    'protocol': 'https',
                    'domain': 'talent.smartlogicapp.com',
                    'uid': uid,
                    'token': token,
                    'user': usuario,
                    'site_name': 'SeniorTalent',
                }
                html = render_to_string(
                    'talent_app/emails/password_reset_email.html', ctx
                )
                try:
                    _send_mail(
                        subject='Recupera tu contraseña en SeniorTalent',
                        message='',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[usuario.email],
                        html_message=html,
                        fail_silently=True,
                    )
                except Exception as e:
                    logger.error(f'Error enviando correo recuperacion a {email}: {e}')
        return redirect('password_reset_done')
    return render(request, 'talent_app/password_reset.html')


def password_reset_confirm_view(request, uidb64, token):
    """Paso 3 — El usuario ingresa su nueva contraseña."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    validlink = False
    usuario = None
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        usuario = Usuario.objects.get(pk=uid)
        if default_token_generator.check_token(usuario, token):
            validlink = True
    except Exception:
        pass

    if request.method == 'POST' and validlink and usuario:
        p1 = request.POST.get('new_password1', '')
        p2 = request.POST.get('new_password2', '')
        if p1 != p2:
            messages.error(request, 'Las contraseñas no coinciden.')
            return render(request, 'talent_app/password_reset_confirm.html', {
                'validlink': True
            })
        try:
            validate_password(p1, usuario)
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)
            return render(request, 'talent_app/password_reset_confirm.html', {
                'validlink': True
            })
        usuario.set_password(p1)
        usuario.save()
        return redirect('password_reset_complete')

    return render(request, 'talent_app/password_reset_confirm.html', {
        'validlink': validlink
    })

# ──────────────────────────────────────────
# PÚBLICAS
# ──────────────────────────────────────────

def home(request):
    pais_codigo = request.pais_codigo
    total = Candidato.objects.filter(estado=Candidato.ESTADO_APROBADO).count()
    total_pais = Candidato.objects.filter(estado=Candidato.ESTADO_APROBADO, pais__codigo=pais_codigo).count()
    sectores = Sector.objects.all()
    total_paises = Pais.objects.filter(activo=True).count()
    return render(request, 'talent_app/home.html', {
        'total': total,
        'total_pais': total_pais,
        'sectores': sectores,
        'total_paises': total_paises,
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
        # Normalizar la entrada del usuario una sola vez
        import unicodedata
        def _normalizar(texto):
            return ''.join(
                c for c in unicodedata.normalize('NFD', texto.lower())
                if unicodedata.category(c) != 'Mn'
            ).strip()

        # Modo activo del buscador (definido en settings.SEARCH_MODE)
        modo = getattr(settings, 'SEARCH_MODE', 'old')
        usado = 'old'  # para log/debug

        # ──────────────────────────────────────────────
        # MODO HÍBRIDO — decide automáticamente entre fulltext y semántica
        # según la naturaleza de la frase del usuario
        # ──────────────────────────────────────────────
        if modo == 'hybrid':
            from .semantic_search import es_consulta_semantica, buscar_candidatos_semantico

            if es_consulta_semantica(q):
                resultados_semanticos = buscar_candidatos_semantico(q, candidatos, limite=10)
                if resultados_semanticos is not None:
                    candidatos = resultados_semanticos
                    usado = 'semantic'
                    # Si la búsqueda semántica devuelve 0, caer a fulltext
                    if not list(candidatos):
                        modo = 'fulltext'
                        usado = 'fulltext_fallback'
                        candidatos = Candidato.objects.filter(
                            estado=Candidato.ESTADO_APROBADO
                        ).select_related('pais').prefetch_related('sectores', 'idiomas')
                else:
                    modo = 'fulltext'
                    usado = 'fulltext_fallback'
            else:
                modo = 'fulltext'
                usado = 'fulltext'

        # ──────────────────────────────────────────────
        # MODO FULLTEXT (también es el fallback de hybrid)
        # ──────────────────────────────────────────────
        if modo == 'fulltext':
            frases = [_normalizar(f) for f in q.split(',') if f.strip()]
            query_total = None
            for frase in frases:
                if not frase:
                    continue
                palabras = frase.split()
                if not palabras:
                    continue
                q_frase = Q()
                for palabra in palabras:
                    palabra_limpia = palabra.strip()
                    if len(palabra_limpia) < 2:
                        continue
                    q_frase &= Q(texto_busqueda__icontains=palabra_limpia)
                query_total = q_frase if query_total is None else (query_total | q_frase)

            if query_total is not None:
                candidatos = candidatos.filter(query_total)

        # ──────────────────────────────────────────────
        # MODO OLD — búsqueda original con unaccent en 8 campos
        # Red de seguridad — se mantiene para poder revertir en 1 segundo
        # ──────────────────────────────────────────────
        elif modo == 'old':
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

            frases = [f.strip() for f in q.split(',') if f.strip()]
            query_total = None
            for frase in frases:
                if not frase:
                    continue
                query_total = filtro_termino(frase) if query_total is None else (query_total | filtro_termino(frase))

            if query_total is not None:
                candidatos = candidatos.filter(query_total).distinct()

        
        logger.info(f'Directorio search | modo={modo} | usado={usado} | q="{q[:60]}"')

    paises   = Pais.objects.filter(activo=True)
    sectores = Sector.objects.all()

    es_empresa_activa = (
        request.user.is_authenticated
        and hasattr(request.user, 'empresa')
        and request.user.empresa.estado == 'activa'
    )

    # Paginación — 12 candidatos por página
    from django.core.paginator import Paginator
    candidatos_lista = list(candidatos) if q else list(candidatos.distinct())
    paginator = Paginator(candidatos_lista, 12)
    pagina_num = request.GET.get('pagina', 1)
    try:
        pagina_num = int(pagina_num)
        if pagina_num < 1:
            pagina_num = 1
    except (ValueError, TypeError):
        pagina_num = 1
    pagina = paginator.get_page(pagina_num)

    return render(request, 'talent_app/directorio.html', {
        'candidatos': pagina,
        'pagina': pagina,
        'paises': paises,
        'sectores': sectores,
        'filtros': request.GET,
        'es_empresa_activa': es_empresa_activa,
    })

def perfil_candidato(request, pk):
    candidato = get_object_or_404(Candidato, pk=pk, estado=Candidato.ESTADO_APROBADO)
    ya_pago = False
    empresa_activa = False
    empresa_obj = None
    if request.user.is_authenticated and hasattr(request.user, 'empresa'):
        empresa_obj = request.user.empresa
        ya_pago = DescargaCV.objects.filter(
            empresa=empresa_obj,
            candidato=candidato,
            estado=DescargaCV.ESTADO_PAGADO
        ).exists()
        empresa_activa = empresa_obj.activa
    return render(request, 'talent_app/perfil_candidato.html', {
        'candidato': candidato,
        'ya_pago': ya_pago,
        'empresa_activa': empresa_activa,
        'empresa': empresa_obj,
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

        if not request.POST.get('acepta_privacidad'):
            messages.error(request, 'Debes aceptar la política de privacidad para registrarte.')
            return render(request, 'talent_app/registro_candidato.html', {'paises': paises})
        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Ya existe una cuenta con ese correo.')
            return render(request, 'talent_app/registro_candidato.html', {'paises': paises})

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            validate_password(password)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
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
        login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, '¡Cuenta creada! Completa tu perfil y sube tu CV.')
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            send_mail(
                subject=f'🆕 Nuevo candidato registrado: {nombre}',
                message='',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=['juansalasa@gmail.com'],
                html_message=f"""
                <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:32px;background:#f9f9f9;border-radius:8px;border:1px solid #e8e8e8;">
                    <h2 style="color:#0A0A2E;margin-bottom:4px;">🆕 Nuevo candidato registrado</h2>
                    <p style="color:#888;font-size:13px;margin-top:0;">SeniorTalent · {timezone.now().strftime('%d/%m/%Y %H:%M')}</p>
                    <table style="width:100%;border-collapse:collapse;margin-top:16px;">
                        <tr><td style="padding:8px 0;color:#6b7280;font-size:14px;width:120px;">Nombre</td><td style="padding:8px 0;font-weight:bold;font-size:14px;">{nombre}</td></tr>
                        <tr style="background:#f3f4f6;"><td style="padding:8px;color:#6b7280;font-size:14px;">Email</td><td style="padding:8px;font-size:14px;">{email}</td></tr>
                        <tr><td style="padding:8px 0;color:#6b7280;font-size:14px;">Ciudad</td><td style="padding:8px 0;font-size:14px;">{ciudad}</td></tr>
                    </table>
                    <div style="text-align:center;margin-top:28px;">
                        <a href="https://talent.smartlogicapp.com/admin/talent_app/candidato/"
                        style="background:#0A0A2E;color:#FFD700;padding:12px 28px;border-radius:6px;font-weight:bold;text-decoration:none;font-size:14px;">
                            Ver en el Admin →
                        </a>
                    </div>
                </div>
                """,
                fail_silently=True,
            )
        except Exception:
            pass
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

        # Correo libre — se aceptan todos los proveedores

        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Ya existe una cuenta con ese correo.')
            return render(request, 'talent_app/registro_empresa.html', {'paises': paises})

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(password)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            return render(request, 'talent_app/registro_empresa.html', {'paises': paises})

        usuario = Usuario.objects.create_user(email=email, password=password, tipo=Usuario.TIPO_EMPRESA)
        
        import os
        limite_fundadoras = int(os.getenv('EMPRESAS_FUNDADORAS_LIMITE', 100))
        creditos_fundadora = int(os.getenv('CREDITOS_EMPRESA_FUNDADORA', 5))
        creditos_normal = int(os.getenv('CREDITOS_EMPRESA_NORMAL', 3))
        total_empresas = Empresa.objects.count()
        creditos = creditos_fundadora if total_empresas < limite_fundadoras else creditos_normal

        Empresa.objects.create(
            usuario=usuario,
            nombre=nombre,
            pais_id=pais_id,
            num_tributario=num_tributario,
            creditos_gratuitos=creditos,
        )
        
        login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, '¡Empresa registrada! Tu cuenta será verificada pronto.')
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            send_mail(
                subject=f'🏢 Nueva empresa registrada: {nombre}',
                message='',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=['juansalasa@gmail.com'],
                html_message=f"""
                <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:32px;background:#f9f9f9;border-radius:8px;border:1px solid #e8e8e8;">
                    <h2 style="color:#0A0A2E;margin-bottom:4px;">🏢 Nueva empresa registrada</h2>
                    <p style="color:#888;font-size:13px;margin-top:0;">SeniorTalent · {timezone.now().strftime('%d/%m/%Y %H:%M')}</p>
                    <table style="width:100%;border-collapse:collapse;margin-top:16px;">
                        <tr><td style="padding:8px 0;color:#6b7280;font-size:14px;width:140px;">Empresa</td><td style="padding:8px 0;font-weight:bold;font-size:14px;">{nombre}</td></tr>
                        <tr style="background:#f3f4f6;"><td style="padding:8px;color:#6b7280;font-size:14px;">Email</td><td style="padding:8px;font-size:14px;">{email}</td></tr>
                        <tr><td style="padding:8px 0;color:#6b7280;font-size:14px;">NIT / Tributario</td><td style="padding:8px 0;font-size:14px;">{num_tributario}</td></tr>
                    </table>
                    <div style="text-align:center;margin-top:28px;">
                        <a href="https://talent.smartlogicapp.com/gestion-st-2026/talent_app/empresa/"
                        style="background:#0A0A2E;color:#FFD700;padding:12px 28px;border-radius:6px;font-weight:bold;text-decoration:none;font-size:14px;">
                            Ver en el Admin →
                        </a>
                    </div>
                </div>
                """,
                fail_silently=True,
            )
        except Exception:
            pass
        return redirect('empresa_candidatos')


    return render(request, 'talent_app/registro_empresa.html', {'paises': paises})


def login_view(request):
    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        usuario  = authenticate(request, email=email, password=password)
        if usuario:
            login(request, usuario)
            from django.utils.http import url_has_allowed_host_and_scheme

            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('dashboard')

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
    import os
    whatsapp_number = os.getenv('WHATSAPP_NUMBER', '')
    mensaje_whatsapp = (
        f"Hola, soy {candidato.nombre} ({candidato.usuario.email}), "
        f"profesional registrado en SeniorTalent. Necesito ayuda con..."
    )
    return render(request, 'talent_app/dashboard_candidato.html', {
        'candidato': candidato,
        'total_descargas': descargas,
        'whatsapp_number': whatsapp_number,
        'mensaje_whatsapp': mensaje_whatsapp,
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

       # Recalcular el campo de búsqueda con TODO ya guardado
        # actualizar_texto_busqueda nunca lanza excepción — si falla,
        # el perfil queda guardado igual y se queda con el texto anterior
        actualizar_texto_busqueda(candidato)

        # Disparar la regeneración del embedding en segundo plano (Celery)
        # No bloquea al usuario — el perfil se guarda en segundos y el
        # vector se actualiza en 1-2 segundos detrás del telón.
        try:
            from .tasks import actualizar_embedding_task
            actualizar_embedding_task.delay(candidato.pk)
            logger.info(f'Embedding task encolado para candidato {candidato.pk}')
        except Exception as e:
            logger.error(f'No se pudo encolar embedding para candidato {candidato.pk}: {type(e).__name__}: {e}')

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

    # Verificar magic bytes del PDF (%PDF-)
    encabezado = archivo.read(5)
    archivo.seek(0)
    if encabezado != b'%PDF-':
        return JsonResponse({'error': 'El archivo no es un PDF válido'}, status=400)


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
    # Validar que el task_id sea un UUID válido para evitar sondeo de IDs arbitrarios
    import re
    if not re.match(r'^[0-9a-f-]{36}$', task_id):
        return JsonResponse({'error': 'ID inválido'}, status=400)

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

    import os
    whatsapp_number = os.getenv('WHATSAPP_NUMBER', '')
    mensaje_whatsapp = (
        f"Hola, soy {empresa.nombre} ({empresa.usuario.email}), "
        f"empresa registrada en SeniorTalent for SmartLogicApp. Necesito ayuda con..."
    )
    import os
    whatsapp_number = os.getenv('WHATSAPP_NUMBER', '')
    mensaje_whatsapp = (
        f"Hola, soy {empresa.nombre} ({empresa.usuario.email}), "
        f"empresa registrada en SeniorTalent. Necesito ayuda con..."
    )
    return render(request, 'talent_app/empresa_candidatos.html', {
        'empresa': empresa,
        'descargas': descargas_pagadas,
        'total_invertido': total_invertido,
        'whatsapp_number': whatsapp_number,
        'mensaje_whatsapp': mensaje_whatsapp,
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
                descarga.monto_usd = (session.get('amount_total') or 0) / 100
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
    import unicodedata, re

    def sanitizar_nombre_archivo(nombre):
        # Quitar acentos
        nfkd = unicodedata.normalize('NFKD', nombre)
        sin_acentos = ''.join(c for c in nfkd if not unicodedata.combining(c))
        # Solo letras, números, guion, guion_bajo
        limpio = re.sub(r'[^\w\s-]', '', sin_acentos)
        return limpio.strip().replace(' ', '_')[:80]

    nombre_archivo = f"CV_{sanitizar_nombre_archivo(candidato.nombre)}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'


    return response


def error_403(request, exception=None):
    return render(request, '403.html', status=403)

@login_required
def iniciar_pago(request, candidato_id):
    empresa   = get_object_or_404(Empresa, usuario=request.user)
    candidato = get_object_or_404(Candidato, pk=candidato_id, estado=Candidato.ESTADO_APROBADO)

    # Bloquear si la empresa no está activa
    if not empresa.activa:
        messages.error(request, 'Tu cuenta de empresa debe estar verificada para descargar CVs.')
        logger.warning(f'Intento de pago con empresa no activa: {empresa.nombre} [{empresa.estado}]')
        return redirect('empresa_candidatos')
    
    logger.info(f'Empresa {empresa.nombre} intenta descargar CV de {candidato.nombre}')

    ya_pago = DescargaCV.objects.filter(
        empresa=empresa,
        candidato=candidato,
        estado=DescargaCV.ESTADO_PAGADO
    ).exists()
    if ya_pago:
        logger.info(f'CV ya descargado previamente - empresa: {empresa.nombre}')
        messages.info(request, 'Ya descargaste este CV anteriormente.')
        return redirect('empresa_candidatos')

    # ── Créditos gratuitos ───────────────────────────────────────────────────
    # Si la empresa tiene créditos disponibles, la descarga es gratuita.
    # Se descuenta en transacción atómica para evitar race conditions.
    # El precio siempre viene del admin (pasarela_config.precio_cv), nunca quemado.
    if empresa.tiene_creditos:
        from django.db import transaction
        try:
            with transaction.atomic():
                # Re-leer con lock para evitar descuento doble en clicks simultáneos
                empresa_lock = Empresa.objects.select_for_update().get(pk=empresa.pk)
                if empresa_lock.tiene_creditos:
                    empresa_lock.creditos_usados += 1
                    empresa_lock.save(update_fields=['creditos_usados'])
                    descarga, _ = DescargaCV.objects.get_or_create(
                        empresa=empresa,
                        candidato=candidato,
                        defaults={'estado': DescargaCV.ESTADO_PAGADO, 'monto_usd': 0}
                    )
                    if descarga.estado != DescargaCV.ESTADO_PAGADO:
                        descarga.estado = DescargaCV.ESTADO_PAGADO
                        descarga.monto_usd = 0
                        from django.utils import timezone
                        descarga.pagado_en = timezone.now()
                        descarga.save(update_fields=['estado', 'monto_usd', 'pagado_en'])

                    creditos_restantes = empresa_lock.creditos_disponibles
                    logger.info(
                        f'Descarga gratuita | empresa: {empresa.nombre} | '
                        f'candidato: {candidato.nombre} | '
                        f'creditos restantes: {creditos_restantes}'
                    )

                    if creditos_restantes == 0:
                        messages.success(
                            request,
                            f'CV de {candidato.nombre} descargado. '
                            f'Has usado todos tus créditos gratuitos. '
                            f'A partir de ahora cada descarga tiene un costo.'
                        )
                    else:
                        messages.success(
                            request,
                            f'CV de {candidato.nombre} descargado gratuitamente. '
                            f'Te quedan {creditos_restantes} descarga(s) gratuita(s).'
                        )
                    return redirect('empresa_candidatos')
                else:
                    # Otro proceso consumió el último crédito justo antes — caer a pago
                    logger.info(f'Race condition en creditos — empresa: {empresa.nombre}, cayendo a pago')

        except Exception as e:
            logger.error(f'Error en descarga gratuita — empresa: {empresa.nombre} — {e}')
            messages.error(request, 'Error procesando la descarga. Intenta de nuevo.')
            return redirect('perfil_candidato', pk=candidato_id)

    # ── Flujo de pago normal (sin créditos) ──────────────────────────────────
    try:
        pasarela_config = empresa.pais.pasarela
        if not pasarela_config.activa:
            messages.error(request, 'No hay pasarela de pago activa para tu pais. Contactanos.')
            return redirect('perfil_candidato', pk=candidato_id)
    except Exception:
        messages.error(request, 'No hay pasarela de pago configurada para tu pais. Contactanos.')
        logger.error(f'Sin pasarela configurada para pais: {empresa.pais.nombre}')
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

        # ── Verificar firma Wompi ─────────────────────────────────────
        import hashlib
        evento_nombre  = payload.get('event', '')
        timestamp      = payload.get('timestamp', '')
        checksum       = payload.get('signature', {}).get('checksum', '')
        try:
            from .models import PasarelaPago
            pasarela_co    = PasarelaPago.objects.get(pais__codigo='CO', activa=True)
            webhook_secret = pasarela_co.webhook_secret
            cadena         = f"{evento_nombre}{timestamp}{webhook_secret}"
            firma_esperada = hashlib.sha256(cadena.encode('utf-8')).hexdigest()
            if not checksum or firma_esperada != checksum:
                logger.warning(f'Wompi webhook — firma inválida. Recibido: {checksum}')
                return HttpResponse(status=401)
        except PasarelaPago.DoesNotExist:
            logger.error('Wompi webhook — pasarela CO no encontrada')
            return HttpResponse(status=400)
        # ─────────────────────────────────────────────────────────────

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

@login_required
@require_http_methods(['GET', 'POST'])
def buscar_ofertas_ia(request):
    from django.utils import timezone
    from django.core.cache import cache
    candidato = get_object_or_404(Candidato, usuario=request.user)

    # Reset mensual automático
    hoy = timezone.now().date()
    if (not candidato.busquedas_ia_reset or
        candidato.busquedas_ia_reset.month != hoy.month or
        candidato.busquedas_ia_reset.year != hoy.year):
        candidato.busquedas_ia_usadas = 0
        candidato.busquedas_ia_reset  = hoy
        candidato.save(update_fields=['busquedas_ia_usadas', 'busquedas_ia_reset'])

    if request.method == 'GET':
        return render(request, 'talent_app/buscar_ofertas_ia.html', {
            'candidato': candidato,
            'disponibles': candidato.busquedas_ia_disponibles,
            'ofertas': None,
        })

    # POST — ejecutar búsqueda
    if not candidato.tiene_busquedas_ia:
        messages.error(request, 'Agotaste tus búsquedas este mes. Vuelve el próximo mes.')
        return redirect('buscar_ofertas_ia')

    sectores = ', '.join([s.nombre for s in candidato.sectores.all()])
    habilidades = ', '.join(candidato.habilidades) if candidato.habilidades else ''
    from talent_app.models import IdiomaCandiato
    idiomas_qs = IdiomaCandiato.objects.filter(candidato=candidato)
    idiomas = ', '.join([f"{i.idioma} ({i.nivel})" for i in idiomas_qs]) if idiomas_qs.exists() else 'Español (Nativo)'

    prompt = f"""Eres un experto en reclutamiento de talento senior en Colombia y Latinoamérica.

Analiza este perfil profesional y genera 5 oportunidades laborales específicas para esta persona.

PERFIL:
- Nombre: {candidato.nombre}
- Cargo: {candidato.cargo_actual}
- Experiencia: {candidato.años_experiencia} años
- Ciudad: {candidato.ciudad}, {candidato.pais.nombre}
- Sectores: {sectores}
- Habilidades: {habilidades}
- Resumen: {candidato.resumen[:300] if candidato.resumen else 'No especificado'}
- Idiomas: {idiomas}
- Disponibilidad: {candidato.get_disponibilidad_display()}
- Modalidad: {candidato.get_modalidad_display()}

INSTRUCCIONES:
- Genera 5 oportunidades laborales MUY ESPECÍFICAS para este perfil en Colombia y Latinoamérica
- Los terminos_busqueda deben ser cortos y precisos para encontrar la oferta en Google
- Responde ÚNICAMENTE con JSON válido sin texto adicional ni markdown

FORMATO JSON ESTRICTO:
{{
  "ofertas": [
    {{
      "titulo": "Cargo específico",
      "tipo_empresa": "Tipo de empresa donde aplica",
      "ubicacion": "Ciudad o modalidad",
      "por_que_coincide": "Por qué este perfil es ideal en 1 línea",
      "terminos_busqueda": "Términos cortos y precisos para buscar esta oferta",
      "salario_estimado": "Rango salarial estimado en COP"
    }}
  ]
}}"""

    try:
        import requests as req
        import time as _time
        api_key = settings.GEMINI_API_KEY

        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
        }

        modelos_cache = cache.get('gemini_modelos_disponibles')
        if not modelos_cache:
            try:
                r = req.get(
                    f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}',
                    timeout=10
                )
                todos = r.json().get('models', [])
                modelos_cache = [
                    m['name'].replace('models/', '')
                    for m in todos
                    if 'generateContent' in m.get('supportedGenerationMethods', [])
                    and any(x in m['name'] for x in ['flash', 'pro'])
                    and 'vision' not in m['name']
                    and 'embedding' not in m['name']
                ]
                modelos_cache.sort(key=lambda x: (0 if 'flash' in x else 1))
                cache.set('gemini_modelos_disponibles', modelos_cache, 60 * 60 * 6)
            except Exception:
                modelos_cache = ['gemini-flash-latest', 'gemini-pro-latest']

        texto = None
        ultimo_error = ''
        for modelo in modelos_cache:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}'
            for intento in range(2):
                try:
                    resp = req.post(url, json=payload, timeout=30)
                    data = resp.json()
                    if 'candidates' in data:
                        texto = data['candidates'][0]['content']['parts'][0]['text']
                        break
                    error_code = data.get('error', {}).get('code', 0)
                    ultimo_error = data.get('error', {}).get('message', '')
                    if error_code == 503:
                        _time.sleep(3)
                        continue
                    break
                except Exception as ex:
                    ultimo_error = str(ex)
                    break
            if texto:
                break

        if not texto:
            raise ValueError('IA no disponible en este momento. Intenta en unos minutos.')

        texto_limpio = texto.strip().replace('```json', '').replace('```', '').strip()
        resultado = _json.loads(texto_limpio)
        ofertas = resultado.get('ofertas', [])

    except Exception as e:
        messages.error(request, f'Error al procesar la búsqueda: {str(e)}')
        return redirect('buscar_ofertas_ia')

    candidato.busquedas_ia_usadas += 1
    candidato.busquedas_ia_reset  = hoy
    candidato.save(update_fields=['busquedas_ia_usadas', 'busquedas_ia_reset'])

    return render(request, 'talent_app/buscar_ofertas_ia.html', {
        'candidato': candidato,
        'disponibles': candidato.busquedas_ia_disponibles,
        'ofertas': ofertas,
    })

def privacidad(request):
    return render(request, 'talent_app/privacidad.html')