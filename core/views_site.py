import json
import os
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import FileResponse, Http404
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from .auth import require_admin
from .helpers import get_param, set_param
from .models import Classe


DEFAULT_SITE_CONFIG = {
    'accueilTitre': 'L’avenir commence ici.',
    'accueilSousTitre': 'Une école, mille possibles.',
    'accueilDescription': 'Un cadre bienveillant pour apprendre, grandir et révéler le potentiel de chaque élève.',
    'actualites': [],
    'resultatsTitre': 'La réussite se construit ensemble.',
    'resultatsDescription': 'Chaque parcours compte. Découvrez les résultats et les temps forts de notre communauté scolaire.',
    'fraisDescription': 'Une tarification claire pour accompagner chaque famille tout au long de l’année.',
    'contactAdresse': '',
    'contactEmail': '',
    'contactTelephone': '',
}

TEXT_LIMITS = {
    'accueilTitre': 120,
    'accueilSousTitre': 160,
    'accueilDescription': 1000,
    'resultatsTitre': 160,
    'resultatsDescription': 1500,
    'fraisDescription': 1000,
    'contactAdresse': 300,
    'contactEmail': 254,
    'contactTelephone': 50,
}
NEWS_IMAGE_PATTERN = re.compile(r'^/api/media/actualites/([a-f0-9]{32}\.(?:png|jpe?g|webp))$')


def _news_image_filename(url):
    match = NEWS_IMAGE_PATTERN.fullmatch(url or '')
    return match.group(1) if match else None


def _site_config():
    raw = get_param('site_web_config', '')
    if not raw:
        return DEFAULT_SITE_CONFIG.copy()
    config = json.loads(raw)
    if not isinstance(config, dict):
        raise ValueError('La configuration enregistrée du site doit être un objet JSON.')
    return {**DEFAULT_SITE_CONFIG, **config}


def _validate_site_config(data):
    if not isinstance(data, dict):
        return None, {'error': 'Les paramètres du site doivent être un objet.'}

    config = {}
    for key, limit in TEXT_LIMITS.items():
        value = data.get(key, DEFAULT_SITE_CONFIG[key])
        if not isinstance(value, str):
            return None, {'error': f'Le champ « {key} » doit être du texte.'}
        value = value.strip()
        if len(value) > limit:
            return None, {'error': f'Le champ « {key} » ne peut pas dépasser {limit} caractères.'}
        config[key] = value

    email = config['contactEmail']
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return None, {'error': 'Veuillez saisir une adresse e-mail valide.'}

    news = data.get('actualites', [])
    if not isinstance(news, list) or len(news) > 10:
        return None, {'error': 'Le site peut contenir au maximum 10 actualités.'}

    config['actualites'] = []
    for index, item in enumerate(news):
        if not isinstance(item, dict):
            return None, {'error': f'L’actualité {index + 1} est invalide.'}
        article = {}
        for key, limit in (('titre', 120), ('date', 60), ('categorie', 50), ('description', 600)):
            value = item.get(key, '')
            if not isinstance(value, str):
                return None, {'error': f'Le champ « {key} » de l’actualité {index + 1} doit être du texte.'}
            value = value.strip()
            if len(value) > limit:
                return None, {'error': f'Le champ « {key} » de l’actualité {index + 1} est trop long.'}
            article[key] = value
        if 'image' in item:
            image = item['image']
            if not isinstance(image, str) or len(image) > 255:
                return None, {'error': f'L’image de l’actualité {index + 1} est invalide.'}
            article['image'] = image.strip()
            if article['image'] and not _news_image_filename(article['image']):
                return None, {'error': f'L’image de l’actualité {index + 1} est invalide.'}
        if not article['titre']:
            return None, {'error': f'Le titre de l’actualité {index + 1} est obligatoire.'}
        config['actualites'].append(article)

    return config, None


@api_view(['GET'])
def site_web_public_view(request):
    config = _site_config()
    tarifs = list(Classe.objects.order_by('niveau', 'nom').values(
        'id', 'nom', 'niveau', 'tarif_inscription', 'tarif_ecolage',
        'tarif_fascicule', 'tarif_location',
    ))
    return Response({
        'nom': get_param('nom_etablissement', 'EduFinance'),
        'logo': get_param('logo_url', ''),
        'telephone': get_param('telephone_etablissement', ''),
        'config': config,
        'tarifs': tarifs,
    })


@api_view(['GET', 'POST'])
@require_admin
def site_web_admin_view(request):
    if request.method == 'GET':
        return Response(_site_config())

    config, error = _validate_site_config(request.data)
    if error:
        return Response(error, status=400)

    previous_config = _site_config()
    set_param('site_web_config', json.dumps(config, ensure_ascii=False))
    retained_images = {
        article['image'] for article in config['actualites'] if article.get('image')
    }
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', 'actualites')
    for article in previous_config.get('actualites', []):
        filename = _news_image_filename(article.get('image'))
        if filename and article.get('image') not in retained_images:
            try:
                os.remove(os.path.join(upload_dir, filename))
            except FileNotFoundError:
                pass
    return Response(config)


@api_view(['POST'])
@parser_classes([MultiPartParser])
@require_admin
def site_web_actualite_image_upload_view(request):
    image = request.FILES.get('image')
    if not image:
        return Response({'error': 'Sélectionnez une image à téléverser.'}, status=400)

    extension = os.path.splitext(image.name)[1].lower()
    signatures = {
        '.png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.jpeg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.webp': lambda data: len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP',
    }
    image.seek(0)
    header = image.read(12)
    image.seek(0)
    if extension not in signatures or not signatures[extension](header):
        return Response({'error': 'Format invalide. Utilisez une image PNG, JPG ou WebP.'}, status=400)

    filename = f'{uuid.uuid4().hex}{extension}'
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', 'actualites')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as destination:
        for chunk in image.chunks():
            destination.write(chunk)

    return Response({'image': f'/api/media/actualites/{filename}'})


@api_view(['GET'])
def site_web_actualite_image_view(request, filename):
    if not re.fullmatch(r'[a-f0-9]{32}\.(?:png|jpe?g|webp)', filename):
        raise Http404
    image_path = os.path.join(settings.MEDIA_ROOT, 'uploads', 'actualites', filename)
    if not os.path.isfile(image_path):
        raise Http404
    content_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
    }
    extension = os.path.splitext(filename)[1]
    response = FileResponse(open(image_path, 'rb'), content_type=content_types[extension])
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'public, max-age=3600'
    return response
