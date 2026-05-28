from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('talent_app', '0001_initial'),
    ]

    operations = [
        # 1. Agregar el campo nuevo, vacío por defecto
        migrations.AddField(
            model_name='candidato',
            name='texto_busqueda',
            field=models.TextField(blank=True, default='', editable=False),
        ),

        # 2. Índice en estado (lo usa toda búsqueda del directorio)
        migrations.AddIndex(
            model_name='candidato',
            index=models.Index(fields=['estado'], name='idx_candidato_estado'),
        ),

        # 3. Índice GIN con trigramas para búsqueda rápida en texto
        # pg_trgm es la extensión de PostgreSQL para buscar dentro de texto
        # con LIKE/contiene de forma indexada — escala bien a 100 mil registros
        migrations.RunSQL(
            sql=[
                "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
                "CREATE INDEX IF NOT EXISTS idx_candidato_texto_busqueda_gin "
                "ON talent_app_candidato USING gin (texto_busqueda gin_trgm_ops);",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS idx_candidato_texto_busqueda_gin;",
            ],
        ),
    ]