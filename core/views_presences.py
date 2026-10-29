from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import transaction

from .models import Presence, Eleve, Classe
from .serializers import (
    ClasseSerializer, PresenceEnregistrerSerializer,
)
from .helpers import get_annee_courante, today_iso
from .auth import require_auth


def _libelle_eleve(el):
    return f'{el.nom} {el.prenom}'


@api_view(['GET'])
@require_auth
def feuille_view(request):
    """Feuille d'appel d'une classe pour une date + période données.
    GET /api/presences/feuille?classe_id=X&date=YYYY-MM-DD&periode=matin
    """
    annee = get_annee_courante()
    classes = ClasseSerializer(Classe.objects.all().order_by('niveau', 'nom'), many=True).data
    niveaux = sorted(set(c['niveau'] for c in classes))

    classe_id = request.GET.get('classe_id') or None
    date = request.GET.get('date') or today_iso()
    periode = request.GET.get('periode') or 'matin'

    if not annee or not classe_id:
        return Response({
            'classes': classes, 'niveaux': niveaux, 'classeId': int(classe_id) if classe_id else None,
            'date': date, 'periode': periode, 'eleves': [],
            'annee': None, 'peutModifier': False, 'estAujourdHui': True,
        })

    eleves = Eleve.objects.filter(annee_id=annee.id, classe_id=classe_id).order_by('nom', 'prenom')
    presences = {
        p.eleve_id: p.statut
        for p in Presence.objects.filter(
            annee_id=annee.id, classe_id=classe_id, date_presence=date, periode=periode
        )
    }

    user = request.current_user
    est_aujourd_hui = (date == today_iso())
    peut_modifier = est_aujourd_hui or user.role == 'admin'

    lignes = [{
        'eleve_id': el.id, 'numero': el.numero, 'nom': el.nom, 'prenom': el.prenom,
        'statut': presences.get(el.id),
    } for el in eleves]

    return Response({
        'classes': classes, 'niveaux': niveaux, 'classeId': int(classe_id),
        'date': date, 'periode': periode, 'eleves': lignes,
        'annee': {'id': annee.id, 'libelle': annee.libelle},
        'peutModifier': peut_modifier, 'estAujourdHui': est_aujourd_hui,
    })


@api_view(['POST'])
@require_auth
def enregistrer_view(request):
    """Enregistre (ou met à jour) la feuille d'appel.
    POST /api/presences/enregistrer
    { classe_id, date, periode, lignes: [{eleve_id, statut}] }
    """
    ser = PresenceEnregistrerSerializer(data=request.data)
    if not ser.is_valid():
        return Response({'error': 'Données invalides', 'details': ser.errors}, status=400)

    data = ser.validated_data
    annee = get_annee_courante()
    if not annee:
        return Response({'error': "Aucune année scolaire active"}, status=400)

    user = request.current_user
    est_aujourd_hui = (data['date'] == today_iso())
    if not est_aujourd_hui and user.role != 'admin':
        return Response({'error': "Seul l'admin peut modifier une présence d'un jour passé"}, status=403)

    try:
        classe = Classe.objects.get(id=data['classe_id'])
    except Classe.DoesNotExist:
        return Response({'error': 'Classe introuvable'}, status=404)

    eleve_ids = [ligne['eleve_id'] for ligne in data['lignes']]
    eleves = {
        eleve.id: eleve
        for eleve in Eleve.objects.filter(
            id__in=eleve_ids, annee_id=annee.id, classe_id=classe.id
        )
    }
    if len(eleves) != len(set(eleve_ids)):
        return Response({
            'error': "Un ou plusieurs élèves ne sont pas inscrits dans cette classe pour l'année active",
        }, status=400)

    nb = 0
    with transaction.atomic():
        for ligne in data['lignes']:
            el = eleves[ligne['eleve_id']]
            Presence.objects.update_or_create(
                eleve_id=el.id, annee_id=annee.id,
                date_presence=data['date'], periode=data['periode'],
                defaults={
                    'classe_id': classe.id,
                    'statut': ligne['statut'],
                    'agent': user,
                },
            )
            nb += 1

    return Response({'ok': True, 'enregistres': nb})


@api_view(['GET'])
@require_auth
def grille_view(request):
    """Grille mensuelle : une ligne par élève, une colonne par jour.
    GET /api/presences/grille?classe_id=X&mois=YYYY-MM&periode=matin
    """
    import calendar
    from datetime import date as _date

    annee = get_annee_courante()
    classes = ClasseSerializer(Classe.objects.all().order_by('niveau', 'nom'), many=True).data
    niveaux = sorted(set(c['niveau'] for c in classes))

    classe_id = request.GET.get('classe_id') or None
    mois = request.GET.get('mois') or today_iso()[:7]
    periode = request.GET.get('periode') or 'matin'

    if not annee or not classe_id:
        return Response({
            'classes': classes, 'niveaux': niveaux, 'classeId': int(classe_id) if classe_id else None,
            'mois': mois, 'periode': periode, 'jours': [], 'eleves': [], 'annee': None,
        })

    try:
        y, m = int(mois[:4]), int(mois[5:7])
        nb_jours = calendar.monthrange(y, m)[1]
    except Exception:
        return Response({'error': 'Mois invalide'}, status=400)

    jours = [f'{y:04d}-{m:02d}-{j:02d}' for j in range(1, nb_jours + 1)]

    eleves = Eleve.objects.filter(annee_id=annee.id, classe_id=classe_id).order_by('nom', 'prenom')

    presences = Presence.objects.filter(
        annee_id=annee.id, classe_id=classe_id, periode=periode,
        date_presence__gte=jours[0], date_presence__lte=jours[-1],
    ).values_list('eleve_id', 'date_presence', 'statut')

    par_eleve = {}
    for eleve_id, d, statut in presences:
        par_eleve.setdefault(eleve_id, {})[d] = statut

    lignes = []
    for el in eleves:
        cases = par_eleve.get(el.id, {})
        nb_present = sum(1 for d in jours if cases.get(d) == 'present')
        nb_absent = sum(1 for d in jours if cases.get(d) == 'absent')
        nb_retard = sum(1 for d in jours if cases.get(d) == 'retard')
        lignes.append({
            'eleve_id': el.id, 'numero': el.numero, 'nom': el.nom, 'prenom': el.prenom,
            'cases': {d: cases.get(d) for d in jours},
            'nbPresent': nb_present, 'nbAbsent': nb_absent, 'nbRetard': nb_retard,
        })

    return Response({
        'classes': classes, 'niveaux': niveaux, 'classeId': int(classe_id),
        'mois': mois, 'periode': periode, 'jours': jours,
        'eleves': lignes, 'annee': {'id': annee.id, 'libelle': annee.libelle},
    })