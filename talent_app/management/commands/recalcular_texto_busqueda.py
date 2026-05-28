"""
Recalcula texto_busqueda para todos los candidatos.

Uso normal — solo aprobados (los del directorio):
    python manage.py recalcular_texto_busqueda

Forzar TODOS (incluye pendientes y rechazados):
    python manage.py recalcular_texto_busqueda --todos

Solo uno específico, por id:
    python manage.py recalcular_texto_busqueda --id 5

Este comando se puede correr cuantas veces se quiera. No daña
datos — solo recalcula el campo texto_busqueda. Si algo falla
en un candidato individual, lo reporta y sigue con el siguiente.
"""
import logging
import time
from django.core.management.base import BaseCommand
from django.db import transaction
from talent_app.models import Candidato
from talent_app.search import construir_texto_busqueda

logger = logging.getLogger('talent_app')


class Command(BaseCommand):
    help = 'Recalcula el campo texto_busqueda para los candidatos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--todos',
            action='store_true',
            help='Procesar TODOS los candidatos, no solo los aprobados.',
        )
        parser.add_argument(
            '--id',
            type=int,
            default=None,
            help='Procesar solo el candidato con este id.',
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=100,
            help='Tamaño del lote para procesar (default 100).',
        )

    def handle(self, *args, **options):
        inicio = time.time()

        # Construir queryset según parámetros
        qs = Candidato.objects.all()

        if options['id']:
            qs = qs.filter(pk=options['id'])
            self.stdout.write(f'Modo: candidato individual id={options["id"]}')
        elif options['todos']:
            self.stdout.write('Modo: TODOS los candidatos (incluye pendientes/rechazados)')
        else:
            qs = qs.filter(estado=Candidato.ESTADO_APROBADO)
            self.stdout.write('Modo: solo candidatos aprobados (default)')

        # Optimización: traer las relaciones por adelantado para no
        # hacer N consultas por cada candidato
        qs = qs.select_related('pais').prefetch_related(
            'sectores', 'idiomas', 'experiencias', 'educaciones'
        )

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING('No hay candidatos que procesar.'))
            return

        self.stdout.write(f'Total a procesar: {total}\n')

        batch_size = options['batch']
        procesados = 0
        actualizados = 0
        sin_cambios = 0
        errores = 0

        # Procesar por lotes para no saturar memoria en bases grandes
        for offset in range(0, total, batch_size):
            lote = qs[offset:offset + batch_size]
            with transaction.atomic():
                for candidato in lote:
                    try:
                        texto_nuevo = construir_texto_busqueda(candidato)
                        if candidato.texto_busqueda != texto_nuevo:
                            candidato.texto_busqueda = texto_nuevo
                            candidato.save(update_fields=['texto_busqueda'])
                            actualizados += 1
                        else:
                            sin_cambios += 1
                    except Exception as e:
                        errores += 1
                        msg = f'Error en candidato {candidato.pk} ({candidato.nombre}): {e}'
                        self.stdout.write(self.style.ERROR(msg))
                        logger.error(msg)

                    procesados += 1

            # Mostrar progreso cada lote
            pct = (procesados / total) * 100
            self.stdout.write(f'  Procesados: {procesados}/{total} ({pct:.1f}%)')

        duracion = time.time() - inicio

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('Resumen'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(f'  Total procesados : {procesados}')
        self.stdout.write(self.style.SUCCESS(f'  Actualizados     : {actualizados}'))
        self.stdout.write(f'  Sin cambios      : {sin_cambios}')
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'  Errores          : {errores}'))
        else:
            self.stdout.write(f'  Errores          : {errores}')
        self.stdout.write(f'  Duracion         : {duracion:.2f} segundos')