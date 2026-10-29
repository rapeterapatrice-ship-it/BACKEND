from datetime import datetime, timezone

from django.db import migrations


def create_invoice(Facture, *, telephone, emitted_at, **references):
    facture = Facture.objects.create(
        telephone_etablissement=telephone,
        statut='emise',
        date_emission=emitted_at,
        **references,
    )
    facture.numero = f'FAC-{emitted_at.year}-{facture.id:06d}'
    facture.save(update_fields=['numero'])
    return facture


def backfill_factures(apps, schema_editor):
    Entree = apps.get_model('core', 'Entree')
    Facture = apps.get_model('core', 'Facture')
    FichePaieProf = apps.get_model('core', 'FichePaieProf')
    LocationBook = apps.get_model('core', 'LocationBook')
    Parametre = apps.get_model('core', 'Parametre')

    telephone = Parametre.objects.filter(
        cle='telephone_etablissement',
    ).values_list('valeur', flat=True).first() or ''

    for entree in Entree.objects.order_by('id').iterator():
        if Facture.objects.filter(entree_id=entree.id).exists():
            continue
        location = None
        if entree.type == 'location-livre':
            location = LocationBook.objects.filter(
                annee_id=entree.annee_id,
                num_location=entree.numero,
            ).exclude(id__in=Facture.objects.exclude(
                location_livre_id=None,
            ).values_list('location_livre_id', flat=True)).first()
        create_invoice(
            Facture,
            telephone=telephone,
            emitted_at=entree.created_at or datetime.now(timezone.utc),
            entree_id=entree.id,
            location_livre_id=location.id if location else None,
        )

    for location in LocationBook.objects.order_by('id').iterator():
        if Facture.objects.filter(location_livre_id=location.id).exists():
            continue
        create_invoice(
            Facture,
            telephone=telephone,
            emitted_at=location.created_at or datetime.now(timezone.utc),
            location_livre_id=location.id,
        )

    for fiche in FichePaieProf.objects.filter(est_paye=True).order_by('id').iterator():
        if Facture.objects.filter(fiche_paie_id=fiche.id).exists():
            continue
        create_invoice(
            Facture,
            telephone=telephone,
            emitted_at=fiche.date_paiement or datetime.now(timezone.utc),
            fiche_paie_id=fiche.id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_facture'),
    ]

    operations = [
        migrations.RunPython(backfill_factures, migrations.RunPython.noop),
    ]
