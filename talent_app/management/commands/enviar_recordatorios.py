"""
Management command para enviar recordatorios automáticos.
Busca candidatos que no han completado su perfil en 48h
y empresas con CVs descargados pero sin actividad reciente.

Uso:
    python manage.py enviar_recordatorios

Cron en VPS (cada día a las 9am):
    0 9 * * * /var/www/senior_talent/venv/bin/python /var/www/senior_talent/manage.py enviar_recordatorios
"""

from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from talent_app.models import Candidato, Empresa
from django.db import models

class Command(BaseCommand):
    help = 'Envía recordatorios automáticos a candidatos y empresas'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando envío de recordatorios...')

        total = 0
        total += self._recordatorio_perfil_incompleto()
        total += self._recordatorio_empresa_inactiva()

        self.stdout.write(
            self.style.SUCCESS(f'✓ {total} recordatorios enviados.')
        )

    def _recordatorio_perfil_incompleto(self):
        """
        Candidatos registrados hace más de 48h con perfil incompleto
        (sin cargo, sin experiencia o sin sectores).
        """
        hace_48h = timezone.now() - timedelta(hours=48)
        hace_7d  = timezone.now() - timedelta(days=7)

        candidatos = Candidato.objects.filter(
            creado_en__lte=hace_48h,
            creado_en__gte=hace_7d,
            estado=Candidato.ESTADO_PENDIENTE,
        ).filter(
            models.Q(cargo_actual='') |
            models.Q(años_experiencia=0) |
            models.Q(resumen='')
        ).select_related('usuario')

        count = 0
        for candidato in candidatos:
            try:
                html = render_to_string(
                    'talent_app/emails/recordatorio_perfil.html',
                    {'candidato': candidato}
                )
                msg = EmailMultiAlternatives(
                    subject='Completa tu perfil en SeniorTalent',
                    body=f'Hola {candidato.nombre}, aún tienes campos por completar en tu perfil.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[candidato.usuario.email],
                )
                msg.attach_alternative(html, 'text/html')
                msg.send(fail_silently=True)
                count += 1
                self.stdout.write(f'  → Recordatorio perfil: {candidato.email}')
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ✗ Error con {candidato.usuario.email}: {e}')
                )

        self.stdout.write(f'  Perfiles incompletos: {count} recordatorios enviados')
        return count

    def _recordatorio_empresa_inactiva(self):
        """
        Empresas activas que llevan más de 15 días sin descargar ningún CV.
        """
        hace_15d = timezone.now() - timedelta(days=15)

        empresas = Empresa.objects.filter(
            estado=Empresa.ESTADO_ACTIVA,
        ).filter(
            models.Q(descargas__isnull=True) |
            models.Q(descargas__creado_en__lte=hace_15d)
        ).distinct().select_related('usuario', 'pais')

        count = 0
        for empresa in empresas:
            try:
                html = render_to_string(
                    'talent_app/emails/recordatorio_empresa.html',
                    {'empresa': empresa}
                )
                msg = EmailMultiAlternatives(
                    subject='Nuevo talento senior disponible en SeniorTalent',
                    body=f'Hola {empresa.nombre}, hay nuevos profesionales en el directorio.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[empresa.usuario.email],
                )
                msg.attach_alternative(html, 'text/html')
                msg.send(fail_silently=True)
                count += 1
                self.stdout.write(f'  → Recordatorio empresa: {empresa.usuario.email}')
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ✗ Error con {empresa.usuario.email}: {e}')
                )

        self.stdout.write(f'  Empresas inactivas: {count} recordatorios enviados')
        return count