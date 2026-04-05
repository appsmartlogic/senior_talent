from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Usuario, Pais, Sector, Candidato, ExperienciaLaboral,
    Educacion, IdiomaCandiato, Empresa, DescargaCV, PasarelaPago
)
from django.db import models as db_models
from django.forms import TextInput

@admin.register(Usuario)
class UsuarioAdmin(BaseUserAdmin):
    list_display   = ('email', 'tipo', 'is_active', 'date_joined')
    list_filter    = ('tipo', 'is_active')
    search_fields  = ('email',)
    ordering       = ('-date_joined',)
    fieldsets = (
        (None,          {'fields': ('email', 'password')}),
        ('Información', {'fields': ('tipo',)}),
        ('Permisos',    {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'tipo', 'password1', 'password2')}),
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