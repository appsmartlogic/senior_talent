from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Usuario, Pais, Sector, Candidato, ExperienciaLaboral,
    Educacion, IdiomaCandiato, Empresa, DescargaCV, PasarelaPago
)
from django.db import models as db_models
from django.forms import TextInput
from django.core.mail import send_mail
from django.contrib import messages
from django.conf import settings
import subprocess
import psutil
import redis
from datetime import datetime, timedelta
import time as time_module
from django.utils import timezone
from django.http import HttpResponse
from django.urls import path
from django.template.response import TemplateResponse
from django.utils.html import format_html

@admin.register(Usuario)
class UsuarioAdmin(BaseUserAdmin):
    list_display   = ('email', 'tipo', 'is_active', 'date_joined', 'tiene_perfil')
    list_filter    = ('tipo', 'is_active')
    search_fields  = ('email',)
    ordering       = ('-date_joined',)
    actions        = ['enviar_correo_seguimiento']
    fieldsets = (
        (None,          {'fields': ('email', 'password')}),
        ('Información', {'fields': ('tipo',)}),
        ('Permisos',    {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'tipo', 'password1', 'password2')}),
    )

    @admin.display(description='Perfil completo')
    def tiene_perfil(self, obj):
        tiene = hasattr(obj, 'candidato') or hasattr(obj, 'empresa')
        if tiene:
            return format_html('<span style="color:#22c55e;font-size:16px;">✔</span>')
        return format_html(
            '<span style="color:#ef4444;font-size:16px;cursor:help;" '
            'title="Sin perfil — Selecciona este usuario y en Acciones ejecuta: Enviar correo de seguimiento">✘</span>'
        )


    @admin.action(description='📧 Enviar correo de seguimiento (sin perfil)')
    def enviar_correo_seguimiento(self, request, queryset):
        enviados = 0
        omitidos = 0
        for usuario in queryset:
            tiene_candidato = hasattr(usuario, 'candidato')
            tiene_empresa   = hasattr(usuario, 'empresa')
            if tiene_candidato or tiene_empresa:
                omitidos += 1
                continue
            try:
                send_mail(
                    subject='Completa tu perfil en SeniorTalent',
                    message='',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[usuario.email],
                    html_message=f"""
                        <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:40px 32px;background:#ffffff;border-radius:8px;border:1px solid #e8e8e8;">
                            
                            <div style="text-align:center;margin-bottom:32px;">
                                <h1 style="color:#0A0A2E;font-size:22px;margin:0;">SeniorTalent</h1>
                                <p style="color:#888;font-size:13px;margin:4px 0 0;">talent.smartlogicapp.com</p>
                            </div>

                            <p style="color:#333;font-size:15px;line-height:1.6;">Hola,</p>

                            <p style="color:#333;font-size:15px;line-height:1.6;">
                                Gracias por registrarte en <strong>SeniorTalent</strong>, la plataforma diseñada para conectar 
                                profesionales con experiencia con empresas que valoran el talento senior.
                            </p>

                            <p style="color:#333;font-size:15px;line-height:1.6;">
                                Notamos que tu cuenta fue creada exitosamente, pero tu perfil profesional aún no está completo. 
                                Sin él, las empresas no pueden encontrarte ni contactarte.
                            </p>

                            <div style="background:#f7f7f7;border-left:4px solid #FFD700;padding:16px 20px;margin:24px 0;border-radius:4px;">
                                <p style="margin:0 0 8px;color:#0A0A2E;font-weight:bold;font-size:14px;">Completar tu perfil te permite:</p>
                                <ul style="margin:0;padding-left:18px;color:#444;font-size:14px;line-height:1.8;">
                                    <li>Ser visible ante empresas que buscan tu experiencia</li>
                                    <li>Subir tu hoja de vida para extracción automática con IA</li>
                                    <li>Recibir oportunidades laborales alineadas a tu perfil</li>
                                </ul>
                            </div>

                            <div style="text-align:center;margin:32px 0;">
                                <a href="https://talent.smartlogicapp.com/dashboard/perfil/"
                                style="background:#FFD700;color:#0A0A2E;padding:14px 32px;border-radius:6px;font-weight:bold;text-decoration:none;font-size:15px;display:inline-block;">
                                    Completar mi perfil ahora →
                                </a>
                            </div>

                            <p style="color:#333;font-size:15px;line-height:1.6;">
                                Si tienes alguna duda, responde este correo y con gusto te ayudamos.
                            </p>

                            <hr style="border:none;border-top:1px solid #eee;margin:32px 0;">

                            <p style="color:#333;font-size:14px;margin:0;">Atentamente,</p>
                            <p style="color:#0A0A2E;font-weight:bold;font-size:14px;margin:4px 0 0;">Equipo SeniorTalent</p>
                            <p style="margin:4px 0 0;"><a href="https://talent.smartlogicapp.com" style="color:#888;font-size:13px;">talent.smartlogicapp.com</a></p>

                            <p style="color:#bbb;font-size:11px;margin-top:24px;text-align:center;">
                                Si no creaste esta cuenta, ignora este mensaje.
                            </p>
                        </div>
                        """,
                    fail_silently=False,
                )
                enviados += 1
                time_module.sleep(0.3)

            except Exception as e:
                self.message_user(request, f'Error enviando a {usuario.email}: {e}', level=messages.ERROR)

        self.message_user(
            request,
            f'✅ {enviados} correo(s) enviado(s). {omitidos} omitido(s) (ya tienen perfil).',
            level=messages.SUCCESS
        )

class ExperienciaInline(admin.TabularInline):
    model = ExperienciaLaboral
    extra = 0

class EducacionInline(admin.TabularInline):
    model = Educacion
    extra = 0

from django import forms

IDIOMAS_CHOICES = [
    ('', '-- Seleccione --'),
    ('Español', 'Español'),
    ('Inglés', 'Inglés'),
    ('Portugués', 'Portugués'),
    ('Francés', 'Francés'),
    ('Alemán', 'Alemán'),
    ('Italiano', 'Italiano'),
    ('Mandarín', 'Mandarín'),
    ('Japonés', 'Japonés'),
    ('Árabe', 'Árabe'),
    ('Coreano', 'Coreano'),
    ('Neerlandés', 'Neerlandés'),
]

class IdiomaInlineForm(forms.ModelForm):
    idioma = forms.ChoiceField(choices=IDIOMAS_CHOICES)
    class Meta:
        model = IdiomaCandiato
        fields = '__all__'

class IdiomaInline(admin.TabularInline):
    model = IdiomaCandiato
    form = IdiomaInlineForm
    extra = 0


@admin.register(Candidato)
class CandidatoAdmin(admin.ModelAdmin):
    list_display    = ('nombre', 'cargo_actual', 'pais', 'años_experiencia', 'estado', 'creado_en')
    list_filter     = ('estado', 'pais', 'disponibilidad', 'modalidad')
    search_fields   = ('nombre', 'cargo_actual')
    list_editable   = ('estado',)
    inlines         = [ExperienciaInline, EducacionInline, IdiomaInline]
    readonly_fields = ('creado_en', 'actualizado_en')
    actions = ['enviar_correo_bienvenida', 'notificar_perfil_incompleto']

    @admin.action(description='💌 Enviar correo de bienvenida y confianza')
    def enviar_correo_bienvenida(self, request, queryset):
        enviados = 0
        for candidato in queryset:
            try:
                send_mail(
                    subject='Bienvenido a SeniorTalent — Las empresas vienen a ti',
                    message='',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[candidato.usuario.email],
                    html_message=f"""
                    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:40px 32px;background:#ffffff;border-radius:8px;border:1px solid #e8e8e8;">
                        <div style="text-align:center;margin-bottom:32px;">
                            <h1 style="color:#0A0A2E;font-size:24px;margin:0;">SeniorTalent</h1>
                            <p style="color:#888;font-size:13px;margin:4px 0 0;">talent.smartlogicapp.com</p>
                        </div>
                        <p style="color:#333;font-size:15px;line-height:1.6;">Hola, <strong>{candidato.nombre}</strong>,</p>
                        <p style="color:#333;font-size:15px;line-height:1.6;">
                            Gracias por hacer parte de <strong>SeniorTalent</strong>. Tu experiencia profesional tiene un valor enorme,
                            y queremos asegurarnos de que las empresas correctas puedan encontrarte.
                        </p>
                        <div style="background:#0A0A2E;border-radius:8px;padding:24px 28px;margin:28px 0;text-align:center;">
                            <p style="color:#FFD700;font-size:18px;font-weight:bold;margin:0 0 8px;">
                                Nuestra filosofía es diferente.
                            </p>
                            <p style="color:#ffffff;font-size:14px;line-height:1.7;margin:0;">
                                No queremos que busques empleo.<br>
                                Queremos que las <strong style="color:#FFD700;">empresas vengan a ti.</strong>
                            </p>
                        </div>
                        <p style="color:#333;font-size:15px;line-height:1.6;">
                            Tu perfil ya está visible para empresas que buscan profesionales con tu nivel de experiencia.
                            Cada día, nuevas empresas ingresan a SeniorTalent buscando exactamente el talento que tú tienes.
                        </p>
                        <div style="background:#f7f7f7;border-left:4px solid #FFD700;padding:16px 20px;margin:24px 0;border-radius:4px;">
                            <p style="margin:0 0 8px;color:#0A0A2E;font-weight:bold;font-size:14px;">¿Qué puedes esperar?</p>
                            <ul style="margin:0;padding-left:18px;color:#444;font-size:14px;line-height:1.9;">
                                <li>Empresas que contactan directamente a perfiles como el tuyo</li>
                                <li>Oportunidades alineadas a tu experiencia y disponibilidad</li>
                                <li>Un proceso sin filtros arbitrarios ni ATS que ignoran tu trayectoria</li>
                            </ul>

                        </div>

                        <div style="background:#0A0A2E;border-radius:8px;padding:20px 24px;margin:24px 0;">
                            <p style="color:#FFD700;font-weight:bold;font-size:15px;margin:0 0 8px;">🚀 ¡Ahora puedes explorar ofertas laborales reales con Inteligencia Artificial!</p>
                            <p style="color:#ccc;font-size:14px;line-height:1.7;margin:0 0 16px;">
                                Desde tu panel encontrarás el botón <strong style="color:#FFD700;">"Buscar ofertas →"</strong>
                                que analiza tu perfil completo y genera oportunidades laborales personalizadas para ti,
                                con los términos exactos para encontrarlas en las principales bolsas de empleo del mundo.
                                Sin buscar manualmente. Sin perder tiempo.
                            </p>
                            <div style="text-align:center;">
                                <a href="https://talent.smartlogicapp.com/dashboard/buscar-ofertas/"
                                   style="background:#FFD700;color:#0A0A2E;padding:12px 28px;border-radius:6px;font-weight:bold;text-decoration:none;font-size:14px;display:inline-block;">
                                    🔍 Buscar mis ofertas con IA →
                                </a>
                            </div>
                        </div>

                        <div style="background:#E1F5EE;border-radius:8px;padding:16px 20px;margin:24px 0;">
                            <p style="color:#0F6E56;font-weight:bold;font-size:14px;margin:0 0 8px;">🏢 Las empresas también te buscan a ti</p>
                            <p style="color:#444;font-size:14px;line-height:1.7;margin:0;">
                                Tu perfil es visible en nuestro directorio profesional. Las empresas registradas en SeniorTalent
                                pueden encontrarte, revisar tu experiencia y contactarte directamente.
                                <strong>No tienes que ir a buscar empleo — deja que tu talento hable por ti.</strong>
                            </p>
                        </div>

                        <div style="background:#f0f7ff;border:1px solid #d0e8ff;border-radius:8px;padding:16px 20px;margin:24px 0;">
                            <p style="margin:0 0 8px;color:#0A0A2E;font-weight:bold;font-size:14px;">🔒 Tu privacidad es nuestra prioridad</p>
                            <ul style="margin:0;padding-left:18px;color:#444;font-size:14px;line-height:1.9;">
                                <li>Tu hoja de vida <strong>no es almacenada</strong> en nuestros servidores</li>
                                <li>Nuestra IA solo la lee para ayudarte a completar tu perfil automáticamente</li>
                                <li>Únicamente guardamos tu <strong>nombre</strong> y <strong>correo electrónico</strong></li>
                                <li>Nunca compartimos tu información sin tu consentimiento</li>
                            </ul>
                        </div>

                        <p style="color:#333;font-size:15px;line-height:1.6;">
                            Si deseas actualizar tu perfil o agregar más información, puedes hacerlo en cualquier momento.
                        </p>
                        <div style="text-align:center;margin:32px 0;">
                            <a href="https://talent.smartlogicapp.com/dashboard/perfil/"
                               style="background:#FFD700;color:#0A0A2E;padding:14px 32px;border-radius:6px;font-weight:bold;text-decoration:none;font-size:15px;display:inline-block;">
                                Ver mi perfil →
                            </a>
                        </div>
                        <hr style="border:none;border-top:1px solid #eee;margin:32px 0;">
                        <p style="color:#333;font-size:14px;margin:0;">Atentamente,</p>
                        <p style="color:#0A0A2E;font-weight:bold;font-size:14px;margin:4px 0 0;">Equipo SeniorTalent</p>
                        <p style="margin:4px 0 0;"><a href="https://talent.smartlogicapp.com" style="color:#888;font-size:13px;">talent.smartlogicapp.com</a></p>
                        <p style="color:#bbb;font-size:11px;margin-top:24px;text-align:center;">
                            Recibiste este correo porque tienes una cuenta registrada en SeniorTalent.
                        </p>
                    </div>
                    """,
                    fail_silently=False,
                )
                enviados += 1
                time_module.sleep(0.3)

            except Exception as e:
                self.message_user(request, f'Error enviando a {candidato.usuario.email}: {e}', level=messages.ERROR)

        self.message_user(
            request,
            f'💌 {enviados} correo(s) de bienvenida enviado(s).',
            level=messages.SUCCESS
        )

    @admin.action(description='⚠️ Notificar perfil incompleto o con errores')
    def notificar_perfil_incompleto(self, request, queryset):
        enviados = 0
        for candidato in queryset:
            try:
                send_mail(
                    subject='Acción requerida: revisa tu perfil en SeniorTalent',
                    message='',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[candidato.usuario.email],
                    html_message=f"""
                    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:40px 32px;background:#ffffff;border-radius:8px;border:1px solid #e8e8e8;">

                        <div style="text-align:center;margin-bottom:32px;">
                            <h1 style="color:#0A0A2E;font-size:22px;margin:0;">SeniorTalent</h1>
                            <p style="color:#888;font-size:13px;margin:4px 0 0;">talent.smartlogicapp.com</p>
                        </div>

                        <p style="color:#333;font-size:15px;line-height:1.6;">Hola, <strong>{candidato.nombre}</strong>,</p>

                        <p style="color:#333;font-size:15px;line-height:1.6;">
                            Revisamos tu perfil en <strong>SeniorTalent</strong> y notamos que algunos datos
                            no se guardaron correctamente o están incompletos.
                        </p>

                        <div style="background:#fff8e1;border-left:4px solid #FFD700;padding:16px 20px;margin:24px 0;border-radius:4px;">
                            <p style="margin:0 0 8px;color:#0A0A2E;font-weight:bold;font-size:14px;">¿Qué debes hacer?</p>
                            <ol style="margin:0;padding-left:18px;color:#444;font-size:14px;line-height:1.9;">
                                <li>Ingresa con tu correo <strong>{candidato.usuario.email}</strong></li>
                                <li>Ve a <strong>Editar perfil</strong></li>
                                <li>Revisa que tus datos estén completos y correctos</li>
                                <li>Haz clic en <strong>Guardar</strong> para confirmar</li>
                            </ol>
                        </div>

                        <p style="color:#333;font-size:14px;line-height:1.6;background:#f7f7f7;padding:12px 16px;border-radius:6px;">
                            Verifica especialmente: cargo actual, resumen profesional, sectores, habilidades e idiomas.
                            Estos campos son los que las empresas ven primero al buscar talento.
                        </p>

                        <div style="text-align:center;margin:32px 0;">
                            <a href="https://talent.smartlogicapp.com/dashboard/perfil/"
                               style="background:#FFD700;color:#0A0A2E;padding:14px 32px;border-radius:6px;font-weight:bold;text-decoration:none;font-size:15px;display:inline-block;">
                                Revisar mi perfil →
                            </a>
                        </div>

                        <p style="color:#333;font-size:15px;line-height:1.6;">
                            Si tienes dudas o necesitas ayuda, responde este correo y te asistimos de inmediato.
                        </p>

                        <hr style="border:none;border-top:1px solid #eee;margin:32px 0;">
                        <p style="color:#333;font-size:14px;margin:0;">Atentamente,</p>
                        <p style="color:#0A0A2E;font-weight:bold;font-size:14px;margin:4px 0 0;">Equipo SeniorTalent</p>
                        <p style="margin:4px 0 0;"><a href="https://talent.smartlogicapp.com" style="color:#888;font-size:13px;">talent.smartlogicapp.com</a></p>

                        <p style="color:#bbb;font-size:11px;margin-top:24px;text-align:center;">
                            Recibiste este correo porque tienes una cuenta registrada en SeniorTalent.
                        </p>
                    </div>
                    """,
                    fail_silently=False,
                )
                enviados += 1
                time_module.sleep(0.3)
            except Exception as e:
                self.message_user(request, f'Error enviando a {candidato.usuario.email}: {e}', level=messages.ERROR)

        self.message_user(
            request,
            f'⚠️ {enviados} notificacion(es) de perfil incompleto enviada(s).',
            level=messages.SUCCESS
        )

@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'pais', 'num_tributario', 'estado', 'creado_en')
    list_filter   = ('estado', 'pais')
    search_fields = ('nombre', 'num_tributario')
    list_editable = ('estado',)


    def save_model(self, request, obj, form, change):
        if change:
            anterior = Empresa.objects.get(pk=obj.pk)
            if anterior.estado != 'activa' and obj.estado == 'activa':
                super().save_model(request, obj, form, change)
                from .emails import enviar_email_empresa_activa
                enviar_email_empresa_activa(obj)
                return
        super().save_model(request, obj, form, change)

@admin.register(DescargaCV)
class DescargaCVAdmin(admin.ModelAdmin):
    list_display    = ('empresa', 'candidato', 'monto_usd', 'estado', 'creado_en')
    list_filter     = ('estado',)
    readonly_fields = ('stripe_payment_id', 'stripe_session_id', 'creado_en', 'pagado_en')


admin.site.register(Pais)
admin.site.register(Sector)


@admin.register(PasarelaPago)
class PasarelaPagoAdmin(admin.ModelAdmin):
    list_display  = ('pais', 'pasarela', 'moneda', 'precio_cv', 'activa', 'actualizado_en')
    list_filter   = ('pasarela', 'activa')
    list_editable = ('activa',)
    readonly_fields = ('creado_en', 'actualizado_en')
    formfield_overrides = {
        db_models.CharField: {'widget': TextInput(attrs={'style': 'width: 600px;'})},
    }
    fieldsets = (
        ('País y pasarela', {
            'fields': ('pais', 'pasarela', 'moneda', 'precio_cv', 'activa')
        }),
        ('Claves de integración', {
            'fields': ('public_key', 'secret_key', 'webhook_secret'),
            'classes': ('collapse',),
            'description': 'Las claves se almacenan de forma segura.'
        }),
        ('Notas internas', {
            'fields': ('notas',),
            'classes': ('collapse',),
        }),
        ('Fechas', {
            'fields': ('creado_en', 'actualizado_en'),
            'classes': ('collapse',),
        }),
    )


# ─── PANEL DE DIAGNÓSTICO ────────────────────────────────────────────────────

class DiagnosticoAdmin(admin.ModelAdmin):
    pass

from django.contrib.admin import AdminSite

import socket

def _check_service(nombre):
    """Verifica por puerto en vez de systemctl"""
    puertos = {
        'gunicorn-seniortalent': 8001,
        'senior_talent_celery': None,
    }
    puerto = puertos.get(nombre)
    if puerto:
        try:
            s = socket.create_connection(('127.0.0.1', puerto), timeout=2)
            s.close()
            return True
        except Exception:
            return False
    # Para Celery verificamos por proceso
    try:
        r = subprocess.run(
            ['/usr/bin/pgrep', '-f', 'celery'],
            capture_output=True, timeout=3
        )
        return r.returncode == 0

    except Exception:
        return False
    
def _check_redis():
    try:
        r = redis.Redis(host='127.0.0.1', port=6379, db=2, socket_timeout=3)
        r.ping()
        return True
    except Exception:
        return False

def _check_postgres():
    from django.db import connection
    try:
        connection.ensure_connection()
        return True
    except Exception:
        return False

def _get_journal_errors(servicio, lineas=8):
    try:
        r = subprocess.run(
            ['journalctl', '-u', servicio, '-n', str(lineas),
             '--no-pager', '--output=short'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip()
    except Exception:
        return 'No disponible'

def _semaforo(ok, texto_ok, texto_fail):
    if ok:
        return f'<span style="color:#22c55e;font-weight:bold;">● {texto_ok}</span>'
    return f'<span style="color:#ef4444;font-weight:bold;">● {texto_fail}</span>'


def diagnostico_view(request):
    # Servicios
    gunicorn_ok  = _check_service('gunicorn-seniortalent')
    celery_ok    = _check_service('senior_talent_celery')
    redis_ok     = _check_redis()
    postgres_ok  = _check_postgres()

    # Sistema
    disco        = psutil.disk_usage('/')
    ram          = psutil.virtual_memory()
    cpu          = psutil.cpu_percent(interval=1)

    # Métricas app
    from talent_app.models import Usuario, Candidato
    from django.utils import timezone
    hoy          = timezone.now().date()
    usuarios_hoy = Usuario.objects.filter(date_joined__date=hoy).count()
    total_users  = Usuario.objects.count()
    sin_perfil   = Usuario.objects.filter(candidato__isnull=True, empresa__isnull=True).count()
    total_cands  = Candidato.objects.count()
    pendientes   = Candidato.objects.filter(estado='pendiente').count()
    aprobados    = Candidato.objects.filter(estado='aprobado').count()

    # Logs recientes
    logs_gunicorn = _get_journal_errors('gunicorn-seniortalent')
    logs_celery   = _get_journal_errors('senior_talent_celery')

    # Tareas Celery fallidas
    try:
        from django_celery_results.models import TaskResult
        tareas_fallidas = TaskResult.objects.filter(
            status='FAILURE'
        ).order_by('-date_done')[:5]
    except Exception:
        tareas_fallidas = []

    def badge(valor, color):
        return f'<span style="background:{color};color:#fff;padding:3px 10px;border-radius:12px;font-size:13px;font-weight:bold;">{valor}</span>'

    disco_pct   = disco.percent
    disco_color = '#22c55e' if disco_pct < 70 else ('#f59e0b' if disco_pct < 90 else '#ef4444')
    ram_pct     = ram.percent
    ram_color   = '#22c55e' if ram_pct < 70 else ('#f59e0b' if ram_pct < 90 else '#ef4444')
    cpu_color   = '#22c55e' if cpu < 70 else ('#f59e0b' if cpu < 90 else '#ef4444')

    html = f"""
    <!DOCTYPE html><html><head>
    <meta charset="utf-8">
    <title>Diagnóstico — SeniorTalent</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #f3f4f6; margin: 0; padding: 24px; color: #1f2937; }}
        h1 {{ color: #0A0A2E; margin-bottom: 4px; }}
        .sub {{ color: #6b7280; font-size: 13px; margin-bottom: 28px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap: 16px; margin-bottom: 28px; }}
        .card {{ background: #fff; border-radius: 10px; padding: 20px 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
        .card h3 {{ margin: 0 0 12px; font-size: 14px; color: #6b7280; text-transform: uppercase; letter-spacing: .5px; }}
        .card .val {{ font-size: 28px; font-weight: bold; color: #0A0A2E; }}
        .card .sub2 {{ font-size: 12px; color: #9ca3af; margin-top: 4px; }}
        .section {{ background: #fff; border-radius: 10px; padding: 20px 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; }}
        .section h2 {{ margin: 0 0 16px; font-size: 16px; color: #0A0A2E; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }}
        .svc-row {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #f3f4f6; }}
        .svc-row:last-child {{ border-bottom: none; }}
        .svc-name {{ font-size: 14px; font-weight: bold; }}
        pre {{ background: #1e1e2e; color: #cdd6f4; padding: 16px; border-radius: 8px; font-size: 11px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto; margin: 0; }}
        .bar-wrap {{ background: #e5e7eb; border-radius: 99px; height: 10px; margin-top: 8px; }}
        .bar {{ height: 10px; border-radius: 99px; }}
        .back-btn {{ display:inline-block; margin-bottom:20px; background:#0A0A2E; color:#fff; padding:8px 18px; border-radius:6px; text-decoration:none; font-size:13px; }}
    </style>
    </head><body>
    <a href="/gestion-st-2026/" class="back-btn">← Volver al admin</a>
    <h1>🔧 Diagnóstico del Sistema</h1>
    <p class="sub">SeniorTalent · talent.smartlogicapp.com · {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>

    <!-- SERVICIOS -->
    <div class="section">
        <h2>⚙️ Estado de Servicios</h2>
        <div class="svc-row">
            <span class="svc-name">Gunicorn (Django)</span>
            {_semaforo(gunicorn_ok, 'Activo', 'Caído')}
        </div>
        <div class="svc-row">
            <span class="svc-name">Celery Worker</span>
            {_semaforo(celery_ok, 'Activo', 'Caído')}
        </div>
        <div class="svc-row">
            <span class="svc-name">Redis</span>
            {_semaforo(redis_ok, 'Conectado', 'Sin conexión')}
        </div>
        <div class="svc-row">
            <span class="svc-name">PostgreSQL</span>
            {_semaforo(postgres_ok, 'Conectado', 'Sin conexión')}
        </div>
    </div>

    <!-- RECURSOS -->
    <div class="section">
        <h2>📊 Recursos del Servidor</h2>
        <div class="svc-row">
            <span class="svc-name">CPU</span>
            <span style="color:{cpu_color};font-weight:bold;">{cpu}%</span>
        </div>
        <div class="svc-row">
            <div style="flex:1">
                <span class="svc-name">RAM — {ram_pct}% ({round(ram.used/1024**3,1)} GB / {round(ram.total/1024**3,1)} GB)</span>
                <div class="bar-wrap"><div class="bar" style="width:{ram_pct}%;background:{ram_color};"></div></div>
            </div>
        </div>
        <div class="svc-row">
            <div style="flex:1">
                <span class="svc-name">Disco — {disco_pct}% ({round(disco.used/1024**3,1)} GB / {round(disco.total/1024**3,1)} GB)</span>
                <div class="bar-wrap"><div class="bar" style="width:{disco_pct}%;background:{disco_color};"></div></div>
            </div>
        </div>
    </div>

    <!-- MÉTRICAS APP -->
    <div class="grid">
        <div class="card">
            <h3>Usuarios totales</h3>
            <div class="val">{total_users}</div>
        </div>
        <div class="card">
            <h3>Registros hoy</h3>
            <div class="val">{usuarios_hoy}</div>
        </div>
        <div class="card">
            <h3>Sin perfil</h3>
            <div class="val" style="color:#ef4444;">{sin_perfil}</div>
            <div class="sub2">usuarios sin completar</div>
        </div>
        <div class="card">
            <h3>Candidatos</h3>
            <div class="val">{total_cands}</div>
            <div class="sub2">{aprobados} aprobados · {pendientes} pendientes</div>
        </div>
    </div>

    <!-- TAREAS FALLIDAS -->
    <div class="section">
        <h2>❌ Últimas Tareas Celery Fallidas</h2>
        {''.join([f'<div class="svc-row"><span style="font-size:13px;">{t.task_name} — <span style="color:#ef4444;">{t.result[:80]}</span></span><span style="color:#9ca3af;font-size:12px;">{t.date_done.strftime("%d/%m %H:%M")}</span></div>' for t in tareas_fallidas]) if tareas_fallidas else '<p style="color:#9ca3af;font-size:13px;">Sin tareas fallidas recientes ✅</p>'}
    </div>

    <!-- LOGS -->
    <div class="section">
        <h2>📋 Logs recientes — Gunicorn</h2>
        <pre>{logs_gunicorn}</pre>
    </div>
    <div class="section">
        <h2>📋 Logs recientes — Celery</h2>
        <pre>{logs_celery}</pre>
    </div>

    </body></html>
    """
    return HttpResponse(html)

from .models import Diagnostico

@admin.register(Diagnostico)
class DiagnosticoMenuAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('', self.admin_site.admin_view(diagnostico_view), name='talent_app_diagnostico_changelist'),
        ]
        return custom + urls

    def changelist_view(self, request, extra_context=None):
        return diagnostico_view(request)