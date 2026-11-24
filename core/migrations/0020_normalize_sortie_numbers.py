import re

from django.db import migrations


def normalize_sortie_numbers(apps, schema_editor):
    AnneeScolaire = apps.get_model('core', 'AnneeScolaire')
    Sortie = apps.get_model('core', 'Sortie')

    for annee in AnneeScolaire.objects.all().iterator():
        match = re.match(r'^\s*(\d{4})', annee.libelle or '')
        if match:
            prefix = match.group(1)[-2:]
        elif annee.debut:
            year_match = re.match(r'^\s*(\d{4})', annee.debut)
            prefix = year_match.group(1)[-2:] if year_match else '00'
        else:
            prefix = '00'

        sorties = Sortie.objects.filter(annee_id=annee.id).order_by('created_at', 'id')
        for index, sortie in enumerate(sorties, start=1):
            sortie.numero = f'{prefix}{index:04d}'
            sortie.save(update_fields=['numero'])


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0019_alter_utilisateur_role_lienparenteleve'),
    ]

    operations = [
        migrations.RunPython(normalize_sortie_numbers, migrations.RunPython.noop),
    ]
