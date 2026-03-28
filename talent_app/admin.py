from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Usuario, Pais, Sector, Candidato, ExperienciaLaboral,
    Educacion, IdiomaCandiato, Empresa, DescargaCV
)


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

class IdiomaInline(admin.TabularInline):
    model = IdiomaCandiato
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


@admin.register(DescargaCV)
class DescargaCVAdmin(admin.ModelAdmin):
    list_display    = ('empresa', 'candidato', 'monto_usd', 'estado', 'creado_en')
    list_filter     = ('estado',)
    readonly_fields = ('stripe_payment_id', 'stripe_session_id', 'creado_en', 'pagado_en')


admin.site.register(Pais)
admin.site.register(Sector)