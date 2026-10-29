import json

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from rest_framework.decorators import api_view
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

    set_param('site_web_config', json.dumps(config, ensure_ascii=False))
    return Response(config)
