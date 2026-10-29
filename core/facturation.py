from django.utils import timezone

from .helpers import get_param
from .models import Facture


def annuler_facture_reservee(facture_id):
    if facture_id:
        Facture.objects.filter(id=facture_id, statut='reservee').update(statut='annulee')


def reserver_facture(request):
    preview = request.session.get('preview') or {}
    save_data = preview.get('saveData') or {}
    annuler_facture_reservee(save_data.get('facture_id'))

    return creer_facture_reservee()


def creer_facture_reservee():
    facture = Facture.objects.create(
        telephone_etablissement=get_param('telephone_etablissement', ''),
    )
    facture.numero = f'FAC-{timezone.localdate().year}-{facture.id:06d}'
    facture.save(update_fields=['numero'])
    return facture


def emettre_facture(facture_id, *, entree=None, location_livre=None, fiche_paie=None):
    facture = Facture.objects.select_for_update().get(id=facture_id, statut='reservee')
    facture.entree = entree
    facture.location_livre = location_livre
    facture.fiche_paie = fiche_paie
    facture.statut = 'emise'
    facture.date_emission = timezone.now()
    facture.save(update_fields=[
        'entree', 'location_livre', 'fiche_paie', 'statut', 'date_emission',
    ])
    return facture
