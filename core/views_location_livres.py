from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import LocationBook, Eleve, Classe, Entree
from .serializers import LocationBookSerializer, ClasseSerializer, AnneeScolaireSerializer, \
    LocationLivresApercuSerializer
from .helpers import get_annee_courante, get_param, today_fr
from .auth import require_auth
from .facturation import annuler_facture_reservee, emettre_facture, reserver_facture


def next_num_location(annee_id):
    cnt = Entree.objects.filter(annee_id=annee_id, type='location-livre').count() + 1
    return 'LOC-' + str(cnt).zfill(4)


@api_view(['GET'])
@require_auth
def location_livres_list_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'locations': [], 'classes': [], 'annee': None})

    locations = LocationBook.objects.select_related(
        'eleve', 'eleve__classe', 'facture',
    ).filter(annee=annee).order_by('-created_at')
    classes = Classe.objects.order_by('niveau', 'nom')
    preview = request.session.get('preview') if request.GET.get('preview') == '1' else None
    if not preview:
        save_data = (request.session.get('preview') or {}).get('saveData') or {}
        annuler_facture_reservee(save_data.get('facture_id'))
        request.session.pop('preview', None)

    return Response({
        'locations': LocationBookSerializer(locations, many=True).data,
        'classes': ClasseSerializer(classes, many=True).data,
        'annee': AnneeScolaireSerializer(annee).data, 'preview': preview,
    })


@api_view(['POST'])
@require_auth
def location_livres_apercu_view(request):
    payload = LocationLivresApercuSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    d = payload.validated_data
    annee = get_annee_courante()

    eleve = Eleve.objects.filter(id=d['eleve_id']).first()
    classe = Classe.objects.filter(id=d['classe_id']).first()
    if not eleve or not classe or not annee:
        return Response({'error': '1'}, status=400)

    montant_total = d['quantite'] * d['montant_unitaire']
    num_loc = next_num_location(annee.id)
    facture = reserver_facture(request)

    preview = {
        'action': 'location-livre',
        'formData': {'eleve_id': d['eleve_id'], 'classe_id': d['classe_id'], 'quantite': d['quantite'],
                     'montant_unitaire': d['montant_unitaire'], 'classe_nom': classe.nom},
        'saveData': {'eleve_id': d['eleve_id'], 'classe_id': d['classe_id'], 'quantite': d['quantite'],
                     'montant_unitaire': d['montant_unitaire'], 'montant_total': montant_total,
                     'num_location': num_loc, 'annee_id': annee.id, 'facture_id': facture.id},
        'facture': {
            'titre': 'REÇU LOCATION DE LIVRES', 'numero': facture.numero, 'date': today_fr(),
            'prenom': eleve.prenom, 'nom': eleve.nom, 'classe': classe.nom,
            'type': f"Location de livres ({d['quantite']} livre(s) × {d['montant_unitaire']} Ar)",
            'montant': montant_total, 'annee': annee.libelle,
            'etablissement': get_param('nom_etablissement', 'EduFinance'), 'logo': get_param('logo_url', ''),
            'telephone': facture.telephone_etablissement,
        }
    }
    request.session['preview'] = preview
    request.session.save()
    return Response({'preview': preview})


@api_view(['POST'])
@require_auth
def location_livres_valider_view(request):
    p = request.session.get('preview')
    if not p:
        return Response({'error': '1'}, status=400)

    annee = get_annee_courante()
    if not annee:
        return Response({'error': '1'}, status=400)

    sd = p['saveData']
    try:
        with transaction.atomic():
            eleve = Eleve.objects.get(id=sd['eleve_id'])
            classe = Classe.objects.get(id=sd['classe_id'])

            location = LocationBook.objects.create(
                eleve=eleve, annee_id=sd['annee_id'], num_location=sd['num_location'],
                quantite=sd['quantite'], montant_unitaire=sd['montant_unitaire'],
                montant_total=sd['montant_total'], agent_id=request.current_user.id,
            )
            entree = Entree.objects.create(
                annee_id=sd['annee_id'], numero=sd['num_location'], date=today_fr(), type='location-livre',
                eleve_nom=f"{eleve.nom} {eleve.prenom}", classe_nom=classe.nom,
                description=f"Location de livres ({sd['quantite']} livre(s)) — {eleve.nom} {eleve.prenom}",
                montant=sd['montant_total'], eleve=eleve, classe=classe, agent_id=request.current_user.id,
            )
            emettre_facture(
                sd['facture_id'], entree=entree, location_livre=location,
            )
    except Exception as e:
        return Response({'error': str(e)}, status=400)

    request.session.pop('preview', None)
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_auth
def location_livres_delete_view(request, location_id):
    location = LocationBook.objects.filter(id=location_id).first()
    if not location:
        return Response({'error': '1'}, status=400)
    try:
        with transaction.atomic():
            Entree.objects.filter(type='location-livre', numero=location.num_location).delete()
            location.delete()
    except Exception as e:
        return Response({'error': str(e)}, status=400)
    return Response({'ok': True})
