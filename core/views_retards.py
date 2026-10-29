from datetime import datetime
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Eleve
from .serializers import AnneeScolaireSerializer, EleveStatusSerializer
from .payment_logic import get_annee_courante, calculate_eleve_status
from .auth import require_auth


def _base_qs(annee):
    return Eleve.objects.select_related('classe').filter(annee=annee).order_by(
        'classe__niveau', 'classe__nom', 'nom', 'prenom')


@api_view(['GET'])
@require_auth
def mois_impayes_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'eleves': [], 'annee': None})

    today = datetime.now()
    eleves_enrichis = []
    for el in _base_qs(annee):
        status = calculate_eleve_status(el, annee, today)
        mois_impayes_noms = ', '.join(m['nom'] for m in status['detailsMois'] if not m['estPaye'])
        mois_en_retard_noms = ', '.join(status['moisEnRetardNoms'])
        mois_non_echus_noms = ', '.join(status['moisImpayesNonEchusNoms'])
        nb_mois_dus = len(status['detailsMois'])
        if status['nbMoisEnRetard'] > 0:
            eleves_enrichis.append({
                'id': el.id, 'numero': el.numero, 'nom': el.nom, 'prenom': el.prenom,
                'classe_nom': el.classe.nom, 'niveau': el.classe.niveau,
                'moisImpayésNoms': mois_impayes_noms,
                'nbMoisImpayés': status['nbMoisImpayes'], 'nbMoisDus': nb_mois_dus,
                'nbMoisEnRetard': status['nbMoisEnRetard'],
                'nbMoisImpayesNonEchus': status['nbMoisImpayesNonEchus'],
                'moisEnRetardNoms': mois_en_retard_noms,
                'moisImpayesNonEchusNoms': mois_non_echus_noms,
                'statut': status['statutGlobal'], 'severite': status['severiteGlobal'],
            })

    return Response({'eleves': eleves_enrichis, 'annee': AnneeScolaireSerializer(annee).data})


@api_view(['GET'])
@require_auth
def en_retard_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'eleves': [], 'annee': None})

    today = datetime.now()
    eleves_enrichis = []
    for el in _base_qs(annee):
        status = calculate_eleve_status(el, annee, today)
        mois_en_retard_noms = ', '.join(status['moisEnRetardNoms'])
        mois_non_echus_noms = ', '.join(status['moisImpayesNonEchusNoms'])
        max_days_overdue = max((m['joursRetardBrut'] for m in status['detailsMois']), default=0)

        eleves_enrichis.append({
            'id': el.id, 'numero': el.numero, 'nom': el.nom, 'prenom': el.prenom,
            'classe_nom': el.classe.nom, 'niveau': el.classe.niveau,
            'nbMoisImpayés': status['nbMoisImpayes'], 'moisImpayésNoms': mois_en_retard_noms,
            'nbMoisEnRetard': status['nbMoisEnRetard'],
            'nbMoisImpayesNonEchus': status['nbMoisImpayesNonEchus'],
            'moisEnRetardNoms': mois_en_retard_noms,
            'moisImpayesNonEchusNoms': mois_non_echus_noms,
            'maxDaysOverdue': max_days_overdue, 'maxDaysLate': status['joursRetardGlobal'],
            'statut': status['statutGlobal'], 'severite': status['severiteGlobal'],
            'montantDu': status['montantDu'],
        })

    eleves_en_retard = [e for e in eleves_enrichis if e['maxDaysLate'] > 0]
    severite_order = {'critical': 0, 'danger': 1, 'warning': 2, 'normal': 3}
    eleves_en_retard.sort(key=lambda e: severite_order.get(e['severite'], 9))

    return Response({'eleves': eleves_en_retard, 'annee': AnneeScolaireSerializer(annee).data})


@api_view(['GET'])
@require_auth
def retards_recherche_view(request):
    annee = get_annee_courante()
    q = (request.GET.get('q') or '').lower()
    if not q or len(q) < 2:
        return Response({'eleves': []})

    eleves = Eleve.objects.select_related('classe').filter(annee=annee).filter(
        Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(numero__icontains=q)
    )[:10]

    today = datetime.now()
    result = []
    for el in eleves:
        status = calculate_eleve_status(el, annee, today)
        mois_impayes_noms = ', '.join(m['nom'] for m in status['detailsMois'] if not m['estPaye'])
        mois_en_retard_noms = ', '.join(status['moisEnRetardNoms'])
        mois_non_echus_noms = ', '.join(status['moisImpayesNonEchusNoms'])
        result.append({
            'id': el.id, 'numero': el.numero, 'nom': el.nom, 'prenom': el.prenom,
            'classe_nom': el.classe.nom, 'niveau': el.classe.niveau,
            'moisImpayésNoms': mois_impayes_noms, 'nbMoisImpayés': status['nbMoisImpayes'],
            'nbMoisEnRetard': status['nbMoisEnRetard'],
            'nbMoisImpayesNonEchus': status['nbMoisImpayesNonEchus'],
            'moisEnRetardNoms': mois_en_retard_noms,
            'moisImpayesNonEchusNoms': mois_non_echus_noms,
            'statut': status['statutGlobal'], 'severite': status['severiteGlobal'],
        })
    return Response({'eleves': result})


@api_view(['GET'])
@require_auth
def retard_detail_view(request, eleve_id):
    annee = get_annee_courante()
    eleve = Eleve.objects.select_related('classe').filter(id=eleve_id, annee=annee).first()
    if not eleve:
        return Response({'error': 'Élève non trouvé'}, status=404)

    status = calculate_eleve_status(eleve, annee, datetime.now())
    for m in status['detailsMois']:
        m['dateFinMois'] = m['dateFinMois'].isoformat()  # non exposé par le serializer, retiré ci-dessous

    status_data = EleveStatusSerializer(status).data
    data = {
        'id': eleve.id, 'numero': eleve.numero, 'nom': eleve.nom, 'prenom': eleve.prenom,
        'classe_nom': eleve.classe.nom, 'niveau': eleve.classe.niveau, 'tarif_ecolage': eleve.classe.tarif_ecolage,
        **status_data,
    }
    return Response({'eleve': data, 'annee': AnneeScolaireSerializer(annee).data})
