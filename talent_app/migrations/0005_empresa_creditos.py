from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('talent_app', '0004_candidato_embedding'),
    ]

    operations = [
        migrations.AddField(
            model_name='empresa',
            name='creditos_gratuitos',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='empresa',
            name='creditos_usados',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]