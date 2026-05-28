# Migración de búsqueda vectorial — fase 2
#
# Agrega tres campos al modelo Candidato:
# - embedding: vector de 768 dimensiones (Gemini embeddings)
# - embedding_modelo: qué modelo generó el vector
# - embedding_actualizado_en: cuándo se generó
#
# Esta migración SÍ se aplica normal con migrate.
# Los 36 candidatos existentes quedarán con embedding = NULL.
# Los embeddings se generarán en fase 3 con Celery + Gemini.

from django.db import migrations, models
import pgvector.django.vector


class Migration(migrations.Migration):

    dependencies = [
        ('talent_app', '0003_sincronizar_historial'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidato',
            name='embedding',
            field=pgvector.django.vector.VectorField(
                blank=True, dimensions=768, editable=False, null=True
            ),
        ),
        migrations.AddField(
            model_name='candidato',
            name='embedding_modelo',
            field=models.CharField(
                blank=True, default='', editable=False, max_length=100
            ),
        ),
        migrations.AddField(
            model_name='candidato',
            name='embedding_actualizado_en',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]