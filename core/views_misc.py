from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Eleve, Classe, MoisEcolage, TypePaiement
from .serializers import EleveSerializer, ClasseSerializer, TypePaiementSerializer, AnneeScolaireSerializer
from .helpers import get_annee_courante
from .payment_logic import get_start_month, get_school_months, get_school_start_year, get_mois_facturables
from .auth import require_auth, require_academic_auth


@api_view(['GET'])
@require_auth
def eleves_by_classe_view(request, classe_id):
    annee = get_annee_courante()
    if not annee:
        return Response([])
    eleves = Eleve.objects.filter(classe_id=classe_id, annee=annee).order_by('nom')
    return Response(EleveSerializer(eleves, many=True).data)


@api_view(['GET'])
@require_auth
def mois_eleve_view(request, eleve_id):
    annee = get_annee_courante()
    if not annee:
        return Response([])
    type_paiement_id = request.GET.get('type_paiement_id')
    qs = MoisEcolage.objects.filter(eleve_id=eleve_id, annee=annee)
    if type_paiement_id and type_paiement_id not in ('null', '0'):
        qs = qs.filter(type_paiement_id=type_paiement_id)
    else:
        qs = qs.filter(type_paiement_id__in=[0])
    return Response(list(qs.values_list('mois_index', flat=True)))


@api_view(['GET'])
@require_auth
def classe_detail_view(request, classe_id):
    classe = Classe.objects.filter(id=classe_id).first()
    return Response(ClasseSerializer(classe).data if classe else {})


@api_view(['GET'])
@require_auth
def eleve_detail_view(request, eleve_id):
    eleve = Eleve.objects.filter(id=eleve_id).first()
    return Response(EleveSerializer(eleve).data if eleve else {})


@api_view(['GET'])
@require_auth
def mois_facturables_view(request, eleve_id):
    annee = get_annee_courante()
    if not annee:
        return Response({'moisFacturables': [], 'moisNonFacturables': []})

    eleve = Eleve.objects.filter(id=eleve_id).first()
    if not eleve:
        return Response({'moisFacturables': [], 'moisNonFacturables': []})

    start_month = get_start_month()
    mois_noms = get_school_months(start_month)
    school_start_year = get_school_start_year(annee, start_month)
    tous_les_mois = list(range(10))
    mois_facturables = get_mois_facturables(
        eleve, start_month, school_start_year, inclure_mois_futurs=True
    )
    mois_facturables_set = set(mois_facturables)
    mois_non_facturables = [m for m in tous_les_mois if m not in mois_facturables_set]

    return Response({
        'moisFacturables': mois_facturables, 'moisNonFacturables': mois_non_facturables,
        'moisFacturablesNoms': ', '.join(mois_noms[i] for i in mois_facturables),
        'moisNonFacturablesNoms': ', '.join(mois_noms[i] for i in mois_non_facturables),
    })


@api_view(['GET'])
@require_auth
def types_paiement_actifs_view(request):
    types = TypePaiement.objects.filter(actif=True).order_by('nom')
    return Response(TypePaiementSerializer(types, many=True).data)


@api_view(['GET'])
@require_academic_auth
def annee_courante_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'id': None, 'libelle': None, 'debut': None})
    return Response(AnneeScolaireSerializer(annee).data)
