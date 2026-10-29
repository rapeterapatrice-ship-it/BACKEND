import os
from django.conf import settings
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from .helpers import get_param, set_param
from .auth import require_admin

ALLOWED_LOGO_EXT = ['.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp']
THEMES_VALIDES = ['green', 'blue', 'purple', 'red', 'orange', 'teal', 'dark']


@api_view(['GET'])
@require_admin
def parametres_view(request):
    return Response({
        'nom': get_param('nom_etablissement', 'EduFinance'),
        'telephone': get_param('telephone_etablissement', ''),
        'theme': get_param('theme_couleur', 'green'),
        'logo': get_param('logo_url', ''),
    })


@api_view(['POST'])
@require_admin
def parametres_nom_view(request):
    v = (request.data.get('nom_etablissement') or '').strip()
    if v:
        set_param('nom_etablissement', v)
    return Response({'ok': True})


@api_view(['POST'])
@require_admin
def parametres_telephone_view(request):
    telephone = request.data.get('telephone_etablissement', '')
    if not isinstance(telephone, str):
        return Response({'error': 'Le numéro de téléphone doit être du texte'}, status=400)
    telephone = telephone.strip()
    if len(telephone) > 50:
        return Response({'error': 'Le numéro de téléphone ne peut pas dépasser 50 caractères'}, status=400)
    set_param('telephone_etablissement', telephone)
    return Response({'ok': True})


@api_view(['POST'])
@require_admin
def parametres_theme_view(request):
    theme = request.data.get('theme_couleur')
    if theme in THEMES_VALIDES:
        set_param('theme_couleur', theme)
    return Response({'ok': True})


@api_view(['POST'])
@parser_classes([MultiPartParser])
@require_admin
def parametres_logo_view(request):
    f = request.FILES.get('logo')
    if not f:
        return Response({'error': 'Aucun fichier'}, status=400)
    if f.size > 2 * 1024 * 1024:
        return Response({'error': 'Fichier trop volumineux (max 2 Mo)'}, status=400)
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_LOGO_EXT:
        return Response({'error': 'Format non autorisé'}, status=400)

    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    for fname in os.listdir(upload_dir):
        if fname.startswith('logo'):
            os.remove(os.path.join(upload_dir, fname))

    dest = os.path.join(upload_dir, 'logo' + ext)
    with open(dest, 'wb+') as dst:
        for chunk in f.chunks():
            dst.write(chunk)

    set_param('logo_url', '/media/uploads/logo' + ext)
    return Response({'ok': True, 'logo_url': '/media/uploads/logo' + ext})


@api_view(['POST'])
@require_admin
def parametres_logo_delete_view(request):
    set_param('logo_url', '')
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
    try:
        for fname in os.listdir(upload_dir):
            if fname.startswith('logo'):
                os.remove(os.path.join(upload_dir, fname))
    except FileNotFoundError:
        pass
    return Response({'ok': True})


@api_view(['GET'])
@require_admin
def parametres_retards_view(request):
    return Response({
        'seuil_leger': get_param('seuil_leger', '10'),
        'seuil_modere': get_param('seuil_modere', '20'),
        'seuil_grave': get_param('seuil_grave', '30'),
        'delai_retard': get_param('delai_retard', '0'),
    })


@api_view(['POST'])
@require_admin
def parametres_retards_update_view(request):
    def to_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    seuil_leger = max(1, to_int(request.data.get('seuil_leger'), 10))
    seuil_modere = max(seuil_leger + 1, to_int(request.data.get('seuil_modere'), 20))
    seuil_grave = max(seuil_modere + 1, to_int(request.data.get('seuil_grave'), 30))
    delai_retard = max(0, to_int(request.data.get('delai_retard'), 0))

    set_param('seuil_leger', str(seuil_leger))
    set_param('seuil_modere', str(seuil_modere))
    set_param('seuil_grave', str(seuil_grave))
    set_param('delai_retard', str(delai_retard))
    return Response({'ok': True})
