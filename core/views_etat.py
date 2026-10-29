from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AnneeScolaire, Entree, Sortie
from .serializers import EntreeSerializer, SortieSerializer, AnneeScolaireSerializer
from .helpers import get_annee_courante
from .auth import require_auth


@api_view(['GET'])
@require_auth
def etat_view(request):
    annee_id = request.GET.get('annee_id')
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    type_entree = request.GET.get('type_entree')

    annees = AnneeScolaireSerializer(AnneeScolaire.objects.order_by('-id'), many=True).data
    courante = get_annee_courante()
    annee_filtre = AnneeScolaire.objects.filter(id=annee_id).first() if annee_id else courante

    if not annee_filtre:
        return Response({'anneeFiltre': None, 'annees': annees, 'totalEntrees': 0, 'totalSorties': 0,
                          'solde': 0, 'byType': [], 'sorties': [], 'entrees': []})

    entrees_qs = Entree.objects.filter(annee=annee_filtre)
    if date_debut:
        entrees_qs = entrees_qs.filter(date__gte=date_debut)
    if date_fin:
        entrees_qs = entrees_qs.filter(date__lte=date_fin)
    if type_entree and type_entree != 'tous':
        entrees_qs = entrees_qs.filter(type=type_entree)
    entrees = EntreeSerializer(entrees_qs.order_by('-created_at'), many=True).data

    sorties_qs = Sortie.objects.filter(annee=annee_filtre)
    if date_debut:
        sorties_qs = sorties_qs.filter(date__gte=date_debut)
    if date_fin:
        sorties_qs = sorties_qs.filter(date__lte=date_fin)
    sorties = SortieSerializer(sorties_qs.order_by('-created_at'), many=True).data

    total_entrees = sum(e['montant'] for e in entrees)
    total_sorties = sum(s['montant'] for s in sorties)

    by_type_map = {}
    for e in entrees:
        by_type_map[e['type']] = by_type_map.get(e['type'], 0) + e['montant']
    by_type = [{'type': t, 'total': v} for t, v in by_type_map.items()]

    return Response({
        'anneeFiltre': AnneeScolaireSerializer(annee_filtre).data,
        'annees': annees, 'totalEntrees': total_entrees, 'totalSorties': total_sorties,
        'solde': total_entrees - total_sorties, 'byType': by_type, 'sorties': sorties, 'entrees': entrees,
    })
