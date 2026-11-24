import calendar
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth import require_admin, require_auth
from .facturation import creer_facture_reservee, emettre_facture
from .helpers import get_annee_courante, get_param, today_fr
from .models import Facture, FichePaieProf, PointageProfesseur, Professeur, Sortie
from .pointage import duree_travail_minutes, pause_recreation

CENTIME = Decimal('0.01')
PRECISION_HEURES = Decimal('0.000001')


def _parse_month(value):
    try:
        mois = datetime.strptime(value, '%Y-%m').date().replace(day=1)
    except (TypeError, ValueError):
        return None
    return mois if mois.strftime('%Y-%m') == value else None


def _calculer_paie(professeur, mois, pause=None):
    dernier_jour = calendar.monthrange(mois.year, mois.month)[1]
    pointages = PointageProfesseur.objects.filter(
        professeur=professeur,
        date__gte=mois,
        date__lte=mois.replace(day=dernier_jour),
        statut__in=('present', 'retard'),
    ).exclude(heure_entree__isnull=True).exclude(heure_sortie__isnull=True)

    total_minutes = 0
    for pointage in pointages:
        total_minutes += duree_travail_minutes(
            pointage.date, pointage.heure_entree, pointage.heure_sortie, pause,
        ) or 0

    total_heures = (
        Decimal(total_minutes) / Decimal(60)
    ).quantize(PRECISION_HEURES, rounding=ROUND_HALF_UP)
    montant_total = (
        Decimal(total_minutes) * professeur.taux_horaire / Decimal(60)
    ).quantize(CENTIME, rounding=ROUND_HALF_UP)
    return total_minutes, total_heures, montant_total


def _facture_data(fiche):
    date_paiement = timezone.localtime(fiche.date_paiement) if fiche.date_paiement else None
    facture = Facture.objects.filter(fiche_paie=fiche).first()
    return {
        'numero': facture.numero if facture else '',
        'date': date_paiement.strftime('%d/%m/%Y %H:%M') if date_paiement else '',
        'etablissement': get_param('nom_etablissement', 'EduFinance'),
        'logo': get_param('logo_url', ''),
        'telephone': facture.telephone_etablissement if facture else get_param('telephone_etablissement', ''),
        'professeur': f'{fiche.professeur.prenom} {fiche.professeur.nom}',
        'mois': fiche.mois.strftime('%Y-%m'),
        'total_heures': str(fiche.total_heures),
        'taux_horaire': str(fiche.taux_horaire),
        'montant_total': str(fiche.montant_total),
    }


@api_view(['GET'])
@require_auth
def salaires_professeurs_view(request):
    mois_param = request.query_params.get('mois') or timezone.localdate().strftime('%Y-%m')
    mois = _parse_month(mois_param)
    if not mois:
        return Response({'error': 'Mois invalide (format attendu : AAAA-MM)'}, status=400)

    pause = pause_recreation()
    professeurs = Professeur.objects.order_by('nom', 'prenom')
    fiches = {
        fiche.professeur_id: fiche
        for fiche in FichePaieProf.objects.filter(professeur__in=professeurs, mois=mois)
    }
    lignes = []
    for professeur in professeurs:
        fiche = fiches.get(professeur.id)
        total_minutes, heures, montant = _calculer_paie(professeur, mois, pause)
        if fiche and fiche.est_paye:
            heures = fiche.total_heures
            montant = fiche.montant_total
            total_minutes = int(
                (fiche.total_heures * 60).to_integral_value(rounding=ROUND_HALF_UP)
            )
        lignes.append({
            'id': professeur.id,
            'nom': professeur.nom,
            'prenom': professeur.prenom,
            'taux_horaire': str(
                fiche.taux_horaire if fiche and fiche.est_paye else professeur.taux_horaire
            ),
            'total_heures': str(heures),
            'total_minutes': total_minutes,
            'montant_total': str(montant),
            'est_paye': bool(fiche and fiche.est_paye),
            'fiche_paie_id': fiche.id if fiche else None,
        })
    return Response({'mois': mois_param, 'professeurs': lignes})


@api_view(['POST'])
@require_admin
def taux_horaire_professeur_view(request, professeur_id):
    try:
        taux = Decimal(str(request.data.get('taux_horaire', '')))
    except (InvalidOperation, TypeError, ValueError):
        return Response({'error': 'Le taux horaire doit être un nombre valide'}, status=400)
    if not taux.is_finite() or taux < 0 or taux > Decimal('99999999.99') or taux.as_tuple().exponent < -2:
        return Response({'error': 'Le taux horaire doit être positif avec au plus deux décimales'}, status=400)

    professeur = Professeur.objects.filter(id=professeur_id).first()
    if not professeur:
        return Response({'error': 'Professeur introuvable'}, status=404)
    professeur.taux_horaire = taux
    professeur.save(update_fields=['taux_horaire'])
    return Response({'ok': True, 'taux_horaire': str(professeur.taux_horaire)})


@api_view(['POST'])
@require_auth
def payer_salaire_professeur_view(request, professeur_id):
    mois_param = request.data.get('mois')
    mois = _parse_month(mois_param)
    if not mois:
        return Response({'error': 'Mois invalide (format attendu : AAAA-MM)'}, status=400)
    annee = get_annee_courante()
    if not annee:
        return Response({'error': 'Aucune année scolaire active pour enregistrer la sortie'}, status=400)
    pause = pause_recreation()

    with transaction.atomic():
        professeur = Professeur.objects.select_for_update().filter(id=professeur_id).first()
        if not professeur:
            return Response({'error': 'Professeur introuvable'}, status=404)

        _, heures, montant = _calculer_paie(professeur, mois, pause)
        fiche, _ = FichePaieProf.objects.get_or_create(
            professeur=professeur,
            mois=mois,
            defaults={
                'total_heures': heures,
                'taux_horaire': professeur.taux_horaire,
                'montant_total': montant,
            },
        )
        if not fiche.est_paye:
            fiche.total_heures = heures
            fiche.taux_horaire = professeur.taux_horaire
            fiche.montant_total = montant
            fiche.est_paye = True
            fiche.date_paiement = timezone.now()
            fiche.save(update_fields=[
                'total_heures', 'taux_horaire', 'montant_total', 'est_paye', 'date_paiement',
            ])
        fiche = FichePaieProf.objects.select_related('professeur').get(id=fiche.id)
        if not Facture.objects.filter(fiche_paie=fiche).exists():
            facture = creer_facture_reservee()
            emettre_facture(facture.id, fiche_paie=fiche)
        if not Sortie.objects.filter(fiche_paie=fiche).exists():
            sortie_numero = 'SOR-' + str(Sortie.objects.filter(annee=annee).count() + 1).zfill(4)
            Sortie.objects.create(
                annee=annee,
                numero=sortie_numero,
                date=today_fr(),
                motif=f'Salaire professeur — {professeur.prenom} {professeur.nom} — {mois_param}',
                montant=fiche.montant_total,
                agent=request.current_user,
                fiche_paie=fiche,
            )

    return Response({'ok': True, 'facture': _facture_data(fiche)})
