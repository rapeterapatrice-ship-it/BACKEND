from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Sortie
from .serializers import SortieSerializer, AnneeScolaireSerializer, SortieAddSerializer
from .helpers import get_annee_courante, today_fr
from .auth import require_admin, require_auth
from decimal import Decimal
import re
from datetime import datetime


def _annee_sortie(annee):
    match = re.match(r'^\s*(\d{4})', annee.libelle or '')
    if match:
        return match.group(1)[-2:]
    if annee.debut:
        try:
            return datetime.strptime(annee.debut[:10], '%Y-%m-%d').strftime('%y')
        except ValueError:
            pass
    return datetime.now().strftime('%y')


def _prochain_numero_sortie(annee):
    prefixe = _annee_sortie(annee)
    pattern = re.compile(rf'^{re.escape(prefixe)}(\d{{4,}})$')
    dernier = 0
    for numero in Sortie.objects.filter(annee=annee).values_list('numero', flat=True):
        match = pattern.fullmatch(numero or '')
        if match:
            dernier = max(dernier, int(match.group(1)))
    return f'{prefixe}{dernier + 1:04d}'


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

    numero = _prochain_numero_sortie(annee)
    Sortie.objects.create(annee=annee, numero=numero, date=today_fr(),
                           motif=payload.validated_data['motif'].strip(),
                           montant=Decimal(payload.validated_data['montant']), agent_id=request.current_user.id)
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_admin
def sortie_delete_view(request, sortie_id):
    sortie = Sortie.objects.filter(id=sortie_id).first()
    if not sortie:
        return Response({'error': 'Sortie introuvable'}, status=404)
    if sortie.fiche_paie_id:
        return Response({'error': 'Une sortie de salaire ne peut pas être supprimée'}, status=400)
    sortie.delete()
    return Response({'ok': True})


@api_view(['POST'])
@require_admin
def sortie_edit_view(request, sortie_id):
    sortie = Sortie.objects.filter(id=sortie_id).first()
    if not sortie:
        return Response({'error': 'Sortie introuvable'}, status=404)
    if sortie.fiche_paie_id:
        return Response({'error': 'Une sortie de salaire ne peut pas être modifiée'}, status=400)

    payload = SortieAddSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    sortie.motif = payload.validated_data['motif'].strip()
    sortie.montant = Decimal(payload.validated_data['montant'])
    sortie.save(update_fields=['motif', 'montant'])
    return Response({'ok': True})
