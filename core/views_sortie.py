from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Sortie
from .serializers import SortieSerializer, AnneeScolaireSerializer, SortieAddSerializer
from .helpers import get_annee_courante, today_fr
from .auth import require_auth


@api_view(['GET'])
@require_auth
def sortie_list_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'sorties': [], 'annee': None})
    sorties = Sortie.objects.filter(annee=annee).order_by('-created_at')
    return Response({
        'sorties': SortieSerializer(sorties, many=True).data,
        'annee': AnneeScolaireSerializer(annee).data,
    })


@api_view(['POST'])
@require_auth
def sortie_add_view(request):
    payload = SortieAddSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    annee = get_annee_courante()
    if not annee:
        return Response({'error': '1'}, status=400)

    cnt = Sortie.objects.filter(annee=annee).count() + 1
    numero = 'SOR-' + str(cnt).zfill(4)
    Sortie.objects.create(annee=annee, numero=numero, date=today_fr(),
                           motif=payload.validated_data['motif'].strip(),
                           montant=payload.validated_data['montant'], agent_id=request.current_user.id)
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_auth
def sortie_delete_view(request, sortie_id):
    Sortie.objects.filter(id=sortie_id).delete()
    return Response({'ok': True})
