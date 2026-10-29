from django.db import IntegrityError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import TypePaiement
from .serializers import TypePaiementSerializer, TypePaiementWriteSerializer
from .auth import require_admin


@api_view(['GET'])
@require_admin
def types_paiement_list_view(request):
    types = TypePaiement.objects.order_by('-created_at')
    return Response({'types': TypePaiementSerializer(types, many=True).data})


@api_view(['POST'])
@require_admin
def types_paiement_add_view(request):
    payload = TypePaiementWriteSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    try:
        payload.save(actif=True)
        return Response({'ok': True})
    except IntegrityError:
        return Response({'error': 'error'}, status=400)


@api_view(['POST', 'PUT'])
@require_admin
def types_paiement_edit_view(request, type_id):
    tp = TypePaiement.objects.filter(id=type_id).first()
    if not tp:
        return Response({'error': 'error'}, status=404)
    payload = TypePaiementWriteSerializer(tp, data=request.data)
    try:
        payload.is_valid(raise_exception=True)
        payload.save()
        return Response({'ok': True})
    except Exception:
        return Response({'error': 'error'}, status=400)


@api_view(['POST'])
@require_admin
def types_paiement_toggle_view(request, type_id):
    tp = TypePaiement.objects.filter(id=type_id).first()
    if tp:
        tp.actif = not tp.actif
        tp.save()
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_admin
def types_paiement_delete_view(request, type_id):
    TypePaiement.objects.filter(id=type_id).delete()
    return Response({'ok': True})
