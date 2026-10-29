"""
Traduction fidèle (1:1) de utils/payment-logic.js
Logique métier de calcul des mois facturables et des retards de paiement.
"""
from datetime import datetime, timedelta
import re

from .models import AnneeScolaire, MoisEcolage, Parametre

ANNEE_MOIS = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
              'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def get_param(key, default=''):
    try:
        p = Parametre.objects.get(cle=key)
        return p.valeur
    except Parametre.DoesNotExist:
        return default


def set_param(key, value):
    Parametre.objects.update_or_create(cle=key, defaults={'valeur': value})


def get_annee_courante():
    return AnneeScolaire.objects.filter(courante=True).first()


def get_start_month():
    # Année scolaire fixe : Septembre à Juin (10 mois)
    return 9


def get_school_months(start_month):
    return [ANNEE_MOIS[(start_month - 1 + i) % 12] for i in range(10)]


def get_school_start_year(annee, start_month):
    if annee and annee.debut:
        d = _parse_date(annee.debut)
        if d:
            return d.year
    if annee and isinstance(annee.libelle, str):
        m = re.match(r'^(\d{4})-(\d{4})$', annee.libelle)
        if m:
            return int(m.group(1))
    today = datetime.now()
    return today.year if (today.month) >= start_month else today.year - 1


def _parse_date(value):
    """Reproduit le comportement de `new Date(value)` puis fallback jj/mm/aaaa de JS."""
    if not value:
        return None
    value = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y/%m/%d'):
        try:
            return datetime.strptime(value[:len(fmt.replace('%f', '000000'))] if False else value, fmt)
        except ValueError:
            pass
    # essai ISO générique
    try:
        return datetime.fromisoformat(value.replace('Z', ''))
    except ValueError:
        pass
    # format jj/mm/aaaa
    parts = value.split('/')
    if len(parts) == 3:
        try:
            return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            return None
    return None


def get_mois_facturables(eleve, start_month, school_start_year, today=None, inclure_mois_futurs=False):
    tous_les_mois = list(range(10))

    date_inscription = getattr(eleve, 'date_inscription', None)
    mois_candidats = tous_les_mois
    d = _parse_date(date_inscription) if date_inscription else None
    if d:
        js_month = d.month
        inscription_year = d.year

        relative_month = js_month - start_month
        if relative_month < 0:
            relative_month += 12

        year_diff = inscription_year - school_start_year
        hors_annee_scolaire = (
            year_diff < 0 or (year_diff == 0 and js_month < start_month)
            or year_diff > 1 or (year_diff == 1 and js_month >= start_month)
        )
        if not hors_annee_scolaire and relative_month < 10:
            mois_candidats = [m for m in tous_les_mois if m >= relative_month]

    if today is None:
        today = datetime.now()
    if inclure_mois_futurs:
        return mois_candidats

    mois_courant = (today.year - school_start_year) * 12 + today.month - start_month
    dernier_mois_exigible = min(9, mois_courant)
    return [m for m in mois_candidats if m <= dernier_mois_exigible]


def get_last_day_of_month(year, month):
    """month est 1-indexé (comme en JS: new Date(year, month, 0).getDate())"""
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def calculate_eleve_status(eleve, annee, today=None):
    if today is None:
        today = datetime.now()
    date_du_jour = today.date() if isinstance(today, datetime) else today

    start_month = get_start_month()
    school_start_year = get_school_start_year(annee, start_month)
    mois_noms = get_school_months(start_month)
    delai_grace_param = int(get_param('delai_retard', '0') or 0)
    seuil_leger = int(get_param('seuil_leger', '10') or 10)
    seuil_modere = int(get_param('seuil_modere', '20') or 20)

    mois_payes = list(
        MoisEcolage.objects.filter(
            eleve=eleve, annee=annee, type_paiement_id=0
        ).values_list('mois_index', flat=True)
    )

    mois_facturables = get_mois_facturables(eleve, start_month, school_start_year, today)

    details_mois = []
    for m_index in mois_facturables:
        est_paye = m_index in mois_payes
        mois_nom = mois_noms[m_index]

        real_month = (start_month - 1) + m_index
        real_year = school_start_year + (real_month // 12)
        real_month = real_month % 12

        dernier_jour = get_last_day_of_month(real_year, real_month + 1)
        date_fin_mois = datetime(real_year, real_month + 1, dernier_jour, 23, 59, 59)

        jours_retard_brut = 0
        if not est_paye and date_du_jour > date_fin_mois.date():
            jours_retard_brut = (date_du_jour - date_fin_mois.date()).days

        details_mois.append({
            'index': m_index,
            'nom': mois_nom,
            'estPaye': est_paye,
            'dateFinMois': date_fin_mois,
            'joursRetardBrut': jours_retard_brut,
        })

    impayes_details = sorted([m for m in details_mois if not m['estPaye']], key=lambda m: m['index'])
    mois_en_retard = [m for m in impayes_details if m['joursRetardBrut'] > 0]
    mois_impayes_non_echus = [m for m in impayes_details if m['joursRetardBrut'] == 0]
    mois_en_retard_effectif = [
        m for m in mois_en_retard
        if m['joursRetardBrut'] > delai_grace_param
    ]

    statut_global = 'À jour'
    severite_global = 'normal'
    jours_retard_global = 0
    plus_ancien_mois = impayes_details[0] if impayes_details else None

    if mois_en_retard_effectif:
        plus_ancien_mois = mois_en_retard_effectif[0]
        jours_retard_effectif = plus_ancien_mois['joursRetardBrut'] - delai_grace_param
        jours_retard_global = jours_retard_effectif
        if len(mois_en_retard_effectif) == 1:
            statut_global = 'Avertissement'
            severite_global = 'warning'
        else:
            statut_global = 'Mise à pied'
            severite_global = 'critical'

    details_enrichis = []
    for m in details_mois:
        jours_effectifs = m['joursRetardBrut']
        if plus_ancien_mois and m['index'] == plus_ancien_mois['index']:
            jours_effectifs = max(0, m['joursRetardBrut'] - delai_grace_param)

        niveau = 'Normal'
        badge = 'badge-gray'
        if not m['estPaye'] and jours_effectifs > 0:
            if jours_effectifs <= seuil_leger:
                niveau = 'Léger'
                badge = 'badge-warning'
            elif jours_effectifs <= seuil_modere:
                niveau = 'Modéré'
                badge = 'badge-danger'
            else:
                niveau = 'Grave'
                badge = 'badge-critical'

        details_enrichis.append({
            **m,
            'joursRetardEffectif': jours_effectifs,
            'niveau': niveau,
            'badge': badge,
            'estLePlusAncien': bool(plus_ancien_mois and m['index'] == plus_ancien_mois['index']),
        })

    return {
        'statutGlobal': statut_global,
        'severiteGlobal': severite_global,
        'joursRetardGlobal': jours_retard_global,
        'nbMoisImpayes': len(impayes_details),
        'nbMoisEnRetard': len(mois_en_retard),
        'nbMoisImpayesNonEchus': len(mois_impayes_non_echus),
        'moisEnRetardNoms': [m['nom'] for m in mois_en_retard],
        'moisImpayesNonEchusNoms': [m['nom'] for m in mois_impayes_non_echus],
        'montantDu': len(impayes_details) * (eleve.classe.tarif_ecolage or 0),
        'detailsMois': details_enrichis,
        'plusAncienMois': plus_ancien_mois['nom'] if plus_ancien_mois else None,
    }
