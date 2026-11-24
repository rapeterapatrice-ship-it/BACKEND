import re

from django.db import migrations


LEGACY_IM = re.compile(r'^(\d{4})-(\d{4,})$')
SCHOOL_YEAR = re.compile(r'^\s*(\d{4})')


def _school_year_prefix(eleve, legacy_prefix):
    match = SCHOOL_YEAR.match(eleve.annee.libelle or '')
    if match:
        return match.group(1)[-2:]
    if eleve.annee.debut:
        match = SCHOOL_YEAR.match(eleve.annee.debut)
        if match:
            return match.group(1)[-2:]
    return legacy_prefix[-2:]


def normalize_student_ims(apps, schema_editor):
    Eleve = apps.get_model('core', 'Eleve')
    updates = []
    reserved_numbers = set(
        Eleve.objects.exclude(numero__isnull=True)
        .exclude(numero='')
        .values_list('numero', flat=True)
    )

    for eleve in Eleve.objects.select_related('annee').order_by('pk').iterator():
        match = LEGACY_IM.fullmatch(eleve.numero or '')
        if not match:
            continue
        numero = f'{_school_year_prefix(eleve, match.group(1))}{match.group(2)}'
        if Eleve.objects.filter(numero=numero).exclude(pk=eleve.pk).exists():
            # Garder l'IM historique en cas de collision afin de ne bloquer ni
            # les données existantes ni les migrations suivantes.
            continue
        if numero in reserved_numbers and numero != eleve.numero:
            continue
        updates.append((eleve.pk, numero))
        reserved_numbers.add(numero)

    for eleve_id, numero in updates:
        Eleve.objects.filter(pk=eleve_id).update(numero=numero)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_sortie_fiche_paie_alter_sortie_montant_and_more'),
    ]

    operations = [
        migrations.RunPython(normalize_student_ims, migrations.RunPython.noop),
    ]
