# Migración de sincronización del historial.
#
# Estos modelos y campos ya existen físicamente en la base de datos
# (fueron aplicados con SQL directo en algún momento), pero el sistema
# de migraciones de Django nunca los registró.
#
# Esta migración se aplica con --fake para que Django solo registre
# en su tabla django_migrations que estos cambios ya están hechos,
# sin ejecutar ningún SQL contra la base de datos.
#
# IMPORTANTE: NO aplicar esta migración con migrate normal.
# Comando correcto: python manage.py migrate talent_app 0003 --fake

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('talent_app', '0002_candidato_texto_busqueda'),
    ]

    operations = [
        migrations.CreateModel(
            name='Diagnostico',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'verbose_name': '🔧 Diagnóstico del Sistema',
                'verbose_name_plural': '🔧 Diagnóstico del Sistema',
                'managed': False,
            },
        ),
        migrations.AddField(
            model_name='pais',
            name='zona_horaria',
            field=models.CharField(default='America/Bogota', help_text='Ejemplo: America/Bogota, America/Mexico_City, Europe/Madrid', max_length=50),
        ),
        migrations.AlterField(
            model_name='descargacv',
            name='monto_usd',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=8, verbose_name='Monto'),
        ),
        migrations.CreateModel(
            name='PasarelaPago',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pasarela', models.CharField(choices=[('stripe', 'Stripe'), ('wompi', 'Wompi'), ('mercadopago', 'MercadoPago'), ('paypal', 'PayPal'), ('payु', 'PayU')], default='stripe', max_length=20)),
                ('public_key', models.CharField(blank=True, max_length=500)),
                ('secret_key', models.CharField(blank=True, max_length=500)),
                ('webhook_secret', models.CharField(blank=True, max_length=500)),
                ('moneda', models.CharField(default='USD', max_length=3)),
                ('precio_cv', models.PositiveIntegerField(default=1, help_text='Indique monto en la moneda local)')),
                ('activa', models.BooleanField(default=True)),
                ('notas', models.TextField(blank=True, help_text='Notas internas sobre esta configuración')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('pais', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='pasarela', to='talent_app.pais')),
            ],
            options={
                'verbose_name': 'Pasarela de pago',
                'verbose_name_plural': 'Pasarelas de pago',
            },
        ),
    ]