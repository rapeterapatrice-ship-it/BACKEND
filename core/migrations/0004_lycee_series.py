from django.db import migrations


def add_lycee_series(apps, schema_editor):
    Classe = apps.get_model('core', 'Classe')
    database = schema_editor.connection.alias

    for niveau_name in ('Première', 'Terminale'):
        generic = Classe.objects.using(database).filter(
            nom=niveau_name, niveau='Lycée',
        ).first()
        ose = Classe.objects.using(database).filter(
            nom=f'{niveau_name} OSE', niveau='Lycée',
        ).first()

        if generic and ose:
            raise RuntimeError(
                f'Les classes « {niveau_name} » et « {niveau_name} OSE » existent toutes les deux. '
                'Fusionnez leurs élèves et tarifs avant cette migration.'
            )

        source = generic or ose
        if not source:
            continue

        if generic:
            generic.nom = f'{niveau_name} OSE'
            generic.save(using=database, update_fields=['nom'])

        for serie in ('S', 'L'):
            Classe.objects.using(database).get_or_create(
                nom=f'{niveau_name} {serie}',
                niveau='Lycée',
                defaults={
                    'tarif_inscription': source.tarif_inscription,
                    'tarif_ecolage': source.tarif_ecolage,
                    'tarif_fascicule': source.tarif_fascicule,
                    'tarif_location': source.tarif_location,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_matiere_professeur_enseignement_evaluation_note'),
    ]

    operations = [
        migrations.RunPython(add_lycee_series, migrations.RunPython.noop),
    ]
