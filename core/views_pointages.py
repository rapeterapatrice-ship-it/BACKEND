import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth import require_auth
from .models import PointageProfesseur, Professeur

POINTAGE_TIME_ZONE = ZoneInfo('Indian/Antananarivo')
STATUTS_POINTAGE = {value for value, _ in PointageProfesseur.STATUT_CHOICES}


def parse_pointage_date(value):
    return parse_date(value) if isinstance(value, str) else None


def _pointage_data(pointage):
    return {
        'id': pointage.id,
        'date': pointage.date.isoformat(),
        'statut': pointage.statut,
        'heure_entree': pointage.heure_entree.strftime('%H:%M') if pointage.heure_entree else None,
        'heure_sortie': pointage.heure_sortie.strftime('%H:%M') if pointage.heure_sortie else None,
        'duree_minutes': (
            int((datetime.combine(pointage.date, pointage.heure_sortie) -
                 datetime.combine(pointage.date, pointage.heure_entree)).total_seconds() // 60)
            if pointage.heure_entree and pointage.heure_sortie else None
        ),
    }


@api_view(['GET'])
@require_auth
def feuille_pointages_view(request):
    mois_param = request.query_params.get('mois')
    if mois_param:
        if request.current_user.role != 'admin':
            return Response({'error': 'La feuille mensuelle est réservée aux administrateurs'}, status=403)
        try:
            debut_mois = datetime.strptime(mois_param, '%Y-%m').date()
            if debut_mois.strftime('%Y-%m') != mois_param:
                raise ValueError
        except ValueError:
            return Response({'error': 'Mois invalide (format attendu : AAAA-MM)'}, status=400)

        dernier_jour = calendar.monthrange(debut_mois.year, debut_mois.month)[1]
        jours = [
            f'{debut_mois.year:04d}-{debut_mois.month:02d}-{jour:02d}'
            for jour in range(1, dernier_jour + 1)
        ]
        professeurs = list(
            Professeur.objects.filter(actif=True).order_by('nom', 'prenom')
        )
        pointages = PointageProfesseur.objects.filter(
            date__gte=debut_mois,
            date__lte=debut_mois.replace(day=dernier_jour),
            professeur__actif=True,
        ).select_related('professeur')
        par_professeur = {professeur.id: {} for professeur in professeurs}
        for pointage in pointages:
            par_professeur[pointage.professeur_id][pointage.date.isoformat()] = _pointage_data(pointage)

        lignes = []
        for professeur in professeurs:
            cases = par_professeur[professeur.id]
            lignes.append({
                'professeur_id': professeur.id,
                'nom': professeur.nom,
                'prenom': professeur.prenom,
                'cases': {jour: cases.get(jour) for jour in jours},
                'nbPresent': sum(1 for pointage in cases.values() if pointage['statut'] == 'present'),
                'nbAbsent': sum(1 for pointage in cases.values() if pointage['statut'] == 'absent'),
                'nbRetard': sum(1 for pointage in cases.values() if pointage['statut'] == 'retard'),
            })

        return Response({
            'mois': mois_param,
            'jours': jours,
            'professeurs': lignes,
            'total': len(lignes),
            'pointes': sum(1 for ligne in lignes if any(ligne['cases'].values())),
            'peutModifier': False,
        })

    if request.current_user.role != 'agent':
        return Response({'error': 'L’opération de pointage est réservée aux agents'}, status=403)

    date_param = request.query_params.get('date')
    date = parse_pointage_date(date_param) if date_param else timezone.localdate(
        timezone=POINTAGE_TIME_ZONE
    )
    if not date:
        return Response({'error': 'Date invalide (format attendu : AAAA-MM-JJ)'}, status=400)

    professeurs = Professeur.objects.filter(actif=True).select_related(
        'utilisateur'
    ).order_by('nom', 'prenom')
    pointages = {
        pointage.professeur_id: pointage
        for pointage in PointageProfesseur.objects.filter(date=date)
    }
    lignes = []
    for professeur in professeurs:
        pointage = pointages.get(professeur.id)
        lignes.append({
            'professeur_id': professeur.id,
            'nom': professeur.nom,
            'prenom': professeur.prenom,
            'pointage': _pointage_data(pointage) if pointage else None,
        })

    est_aujourd_hui = date == timezone.localdate(timezone=POINTAGE_TIME_ZONE)
    return Response({
        'date': date.isoformat(),
        'professeurs': lignes,
        'total': len(lignes),
        'pointes': sum(1 for ligne in lignes if ligne['pointage']),
        'peutModifier': est_aujourd_hui,
    })


@api_view(['POST'])
@require_auth
def enregistrer_pointage_view(request):
    utilisateur = request.current_user
    if utilisateur.role != 'agent':
        return Response({'error': 'Seuls les agents peuvent enregistrer les pointages'}, status=403)
    date = parse_pointage_date(request.data.get('date', ''))
    lignes = request.data.get('lignes')
    if not date:
        return Response({'error': 'Date invalide (format attendu : AAAA-MM-JJ)'}, status=400)
    if date > timezone.localdate(timezone=POINTAGE_TIME_ZONE):
        return Response({'error': 'Le pointage ne peut pas être enregistré pour une date future'}, status=400)
    if date != timezone.localdate(timezone=POINTAGE_TIME_ZONE):
        return Response({'error': 'Un agent ne peut enregistrer que les pointages du jour'}, status=403)
    if not isinstance(lignes, list):
        return Response({'error': 'La liste des pointages est invalide'}, status=400)

    professeur_ids = []
    for ligne in lignes:
        if not isinstance(ligne, dict):
            return Response({'error': 'Une ligne de pointage est invalide'}, status=400)
        try:
            professeur_ids.append(int(ligne.get('professeur_id')))
        except (TypeError, ValueError):
            return Response({'error': 'Identifiant de professeur invalide'}, status=400)
    if len(professeur_ids) != len(set(professeur_ids)):
        return Response({'error': 'Un professeur ne peut apparaître qu’une seule fois'}, status=400)

    professeurs = {
        professeur.id: professeur
        for professeur in Professeur.objects.filter(id__in=professeur_ids, actif=True)
    }
    if len(professeurs) != len(professeur_ids):
        return Response({'error': 'Un ou plusieurs professeurs sont introuvables ou inactifs'}, status=400)

    pointages_valides = []
    for ligne, professeur_id in zip(lignes, professeur_ids):
        statut = ligne.get('statut')
        if statut not in STATUTS_POINTAGE:
            return Response({'error': 'Statut invalide : présent, absent ou retard'}, status=400)
        heure_entree = ligne.get('heure_entree') or None
        heure_sortie = ligne.get('heure_sortie') or None
        if statut == 'absent':
            heure_entree = heure_sortie = None
        elif not heure_entree:
            return Response({'error': "L'heure d'entrée est obligatoire pour un professeur présent ou en retard"}, status=400)
        else:
            entree = parse_time(heure_entree)
            sortie = parse_time(heure_sortie) if heure_sortie else None
            if not entree or (heure_sortie and not sortie):
                return Response({'error': 'Format d’heure invalide (HH:MM)'}, status=400)
            if sortie and sortie < entree:
                return Response({'error': "L'heure de sortie ne peut pas précéder l'entrée"}, status=400)
            heure_entree, heure_sortie = entree, sortie
        pointages_valides.append((professeurs[professeur_id], statut, heure_entree, heure_sortie))

    with transaction.atomic():
        for professeur, statut, heure_entree, heure_sortie in pointages_valides:
            PointageProfesseur.objects.update_or_create(
                professeur=professeur,
                date=date,
                defaults={
                    'statut': statut,
                    'heure_entree': heure_entree,
                    'heure_sortie': heure_sortie,
                },
            )

    return Response({'ok': True, 'enregistres': len(pointages_valides)})


def parse_time(value):
    from datetime import time

    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None
