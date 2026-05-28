"""
Regenera embeddings para los candidatos.

Uso normal — solo aprobados que no tengan embedding:
    python manage.py regenerar_embeddings

Forzar regeneración de TODOS los aprobados (sobrescribe los existentes):
    python manage.py regenerar_embeddings --forzar

Procesar uno específico:
    python manage.py regenerar_embeddings --id 45

Ajustar pausa entre llamadas a Gemini (en segundos, default 0.3):
    python manage.py regenerar_embeddings --pausa 0.5

Por defecto NO sobrescribe embeddings existentes para no gastar API
de más. Use --forzar solo si cambió el modelo o la lógica del texto.
Cada embedding cuesta ~$0.00003 USD. 35 candidatos = ~$0.001 USD total.
"""
import logging
import time
from django.core.management.base import BaseCommand
from talent_app.models import Candidato
from talent_app.embeddings import actualizar_embedding_candidato

logger = logging.getLogger('talent_app')


class Command(BaseCommand):
    help = 'Regenera el campo embedding (vector 768) de los candidatos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar',
            action='store_true',
            help='Sobrescribir embeddings existentes (default: solo los que están NULL).',
        )
        parser.add_argument(
            '--id', 
            type=int,
            default=None,
            help='Procesar solo el candidato con este id.',
        )
        parser.add_argument(
            '--pausa',
            type=float,
            default=0.3,
            help='Segundos entre llamadas a Gemini (default 0.3 — respeta rate limits).',
        )

    def handle(self, *args, **options):
        inicio = time.time()

        # Construir queryset
        qs = Candidato.objects.filter(estado=Candidato.ESTADO_APROBADO)

        if options['id']:
            qs = qs.filter(pk=options['id'])
            self.stdout.write(f'Modo: candidato individual id={options["id"]}')
        elif options['forzar']:
            self.stdout.write(self.style.WARNING(
                'Modo: TODOS los candidatos aprobados (sobrescribe existentes)'
            ))
        else:
            qs = qs.filter(embedding__isnull=True)
            self.stdout.write('Modo: solo candidatos aprobados sin embedding')

        # Optimización: traer las relaciones por adelantado
        qs = qs.select_related('pais').prefetch_related(
            'sectores', 'idiomas', 'experiencias', 'educaciones'
        )

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING('No hay candidatos que procesar.'))
            return

        # Estimación de costo
        costo_estimado = total * 0.00003
        self.stdout.write(f'Total a procesar  : {total}')
        self.stdout.write(f'Costo estimado    : ${costo_estimado:.5f} USD (~$0.00003 c/u)')
        self.stdout.write(f'Pausa entre calls : {options["pausa"]} segundos')
        self.stdout.write('')

        procesados = 0
        ok = 0
        errores = 0

        for candidato in qs:
            try:
                exito = actualizar_embedding_candidato(candidato)
                if exito:
                    ok += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  [{procesados + 1}/{total}] OK   - {candidato.nombre} (id={candidato.pk})'
                    ))
                else:
                    errores += 1
                    self.stdout.write(self.style.ERROR(
                        f'  [{procesados + 1}/{total}] FAIL - {candidato.nombre} (id={candidato.pk})'
                    ))
            except Exception as e:
                errores += 1
                self.stdout.write(self.style.ERROR(
                    f'  [{procesados + 1}/{total}] ERROR - {candidato.nombre} (id={candidato.pk}): {e}'
                ))
                logger.error(f'regenerar_embeddings: candidato {candidato.pk} → {e}')

            procesados += 1

            # Pausa entre llamadas para respetar rate limits de Gemini
            # (Gemini permite 1500 requests/minuto en su plan free)
            if procesados < total:
                time.sleep(options['pausa'])

        duracion = time.time() - inicio

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('Resumen'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(f'  Total procesados : {procesados}')
        self.stdout.write(self.style.SUCCESS(f'  OK               : {ok}'))
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'  Errores          : {errores}'))
        else:
            self.stdout.write(f'  Errores          : {errores}')
        self.stdout.write(f'  Costo real       : ${ok * 0.00003:.5f} USD')
        self.stdout.write(f'  Duracion         : {duracion:.2f} segundos')