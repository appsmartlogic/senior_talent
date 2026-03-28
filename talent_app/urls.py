from django.urls import path
from . import views

urlpatterns = [
    # Públicas
    path('', views.home, name='home'),
    path('directorio/', views.directorio, name='directorio'),
    path('candidato/<int:pk>/', views.perfil_candidato, name='perfil_candidato'),

    # Auth
    path('registro/candidato/', views.registro_candidato, name='registro_candidato'),
    path('registro/empresa/', views.registro_empresa, name='registro_empresa'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard candidato
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/perfil/', views.editar_perfil, name='editar_perfil'),
    path('dashboard/cv/subir/', views.subir_cv_ia, name='subir_cv_ia'),

    # Dashboard empresa
    path('empresa/candidatos/', views.empresa_candidatos, name='empresa_candidatos'),
    path('empresa/descargar/<int:candidato_id>/', views.iniciar_pago, name='iniciar_pago'),

    # Stripe
    path('pago/exito/', views.pago_exito, name='pago_exito'),
    path('pago/cancelado/', views.pago_cancelado, name='pago_cancelado'),
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('empresa/cv/<int:candidato_id>/pdf/', views.descargar_pdf_cv, name='descargar_pdf_cv'),
]