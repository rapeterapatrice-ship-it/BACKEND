from datetime import datetime

from .models import Parametre, AnneeScolaire

MOIS_FULL = ['Septembre', 'Octobre', 'Novembre', 'Décembre', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin']


def get_param(key, default=''):
    try:
        return Parametre.objects.get(cle=key).valeur
    except Parametre.DoesNotExist:
        return default


def set_param(key, value):
    Parametre.objects.update_or_create(cle=key, defaults={'valeur': value})


def get_annee_courante():
    return AnneeScolaire.objects.filter(courante=True).first()


def today_fr():
    return datetime.now().strftime('%d/%m/%Y')


def today_iso():
    return datetime.now().strftime('%Y-%m-%d')


def format_date_fr(date_iso):
    if not date_iso:
        return today_fr()
    try:
        # Accepte YYYY-MM-DD ou format déjà FR
        if '/' in str(date_iso):
            return date_iso
        d = datetime.strptime(str(date_iso)[:10], '%Y-%m-%d')
        return d.strftime('%d/%m/%Y')
    except ValueError:
        return today_fr()


def is_valid_person_name(value):
    import re
    if not isinstance(value, str):
        return False
    return bool(re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$", value.strip()))


def next_num_paiement(annee_id):
    from .models import Entree
    cnt = Entree.objects.filter(annee_id=annee_id).exclude(type__in=['inscription', 'reinscription']).count() + 1
    return 'PAY-' + str(cnt).zfill(4)
