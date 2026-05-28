"""
Asigna créditos gratuitos a las empresas existentes según su orden de registro.
Las primeras N empresas (EMPRESAS_FUNDADORAS_LIMITE) reciben CREDITOS_EMPRESA_FUNDADORA.
Las demás reciben CREDITOS_EMPRESA_NORMAL.

Solo actualiza empresas con creditos_gratuitos == 0 (sin créditos asignados).
Es seguro correr múltiples veces.

Uso:
    python manage.py asignar_creditos_empresas
    python manage.py asignar_creditos_empresas --forzar  # sobrescribe existentes
"""
import os
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from talent_app.models import Empresa

logger = logging.getLogger('talent_app')


class Command(BaseCommand):
    help = 'Asigna créditos gratuitos a empresas existentes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar',
            action='store_true',
            help='Sobrescribir créditos existentes.',
        )

    def handle(self, *args, **options):
        limite_fundadoras = int(os.getenv('EMPRESAS_FUNDADORAS_LIMITE', 100))
        creditos_fundadora = int(os.getenv('CREDITOS_EMPRESA_FUNDADORA', 5))
        creditos_normal = int(os.getenv('CREDITOS_EMPRESA_NORMAL', 3))

        self.stdout.write(f'Limite fundadoras : {limite_fundadoras}')
        self.stdout.write(f'Creditos fundadora: {creditos_fundadora}')
        self.stdout.write(f'Creditos normal   : {creditos_normal}')
        self.stdout.write('')

        empresas = Empresa.objects.order_by('creado_en')
        if not options['forzar']:
            empresas = empresas.filter(creditos_gratuitos=0)

        total = empresas.count()
        if total == 0:
            self.stdout.write(self.style.WARNING('No hay empresas que procesar.'))
            return

        self.stdout.write(f'Empresas a procesar: {total}')
        actualizadas = 0

        with transaction.atomic():
            for i, empresa in enumerate(empresas, start=1):
                posicion_real = Empresa.objects.filter(
                    creado_en__lte=empresa.creado_en
                ).count()
                es_fundadora = posicion_real <= limite_fundadoras
                creditos = creditos_fundadora if es_fundadora else creditos_normal
                empresa.creditos_gratuitos = creditos
                empresa.save(update_fields=['creditos_gratuitos'])
                tipo = 'FUNDADORA' if es_fundadora else 'NORMAL'
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  [{i}/{total}] {empresa.nombre} → {creditos} creditos ({tipo})'
                    )
                )
                actualizadas += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Listo. {actualizadas} empresa(s) actualizadas.'))