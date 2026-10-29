from django.db import IntegrityError, transaction
from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Utilisateur, Classe, AnneeScolaire, Entree, Sortie, Professeur, Enseignement
from .serializers import (
    UtilisateurSerializer, UtilisateurWriteSerializer, ClasseSerializer, ClasseWriteSerializer,
    AnneeScolaireStatsSerializer, AnneeScolaireAddSerializer,
)
from .auth import require_admin, hash_password
from .helpers import get_annee_courante


# ─────────────────────────── PROFESSEURS ───────────────────────────

def _professeur_data(professeur, annee):
    enseignements = professeur.enseignement_set.filter(annee=annee).select_related(
        'classe', 'matiere'
    ).order_by('classe__niveau', 'classe__nom', 'matiere__nom') if annee else []
    return {
        'id': professeur.id,
        'utilisateur_id': professeur.utilisateur_id,
        'has_account': professeur.utilisateur_id is not None,
        'prenom': professeur.prenom,
        'nom': professeur.nom,
        'username': professeur.utilisateur.username if professeur.utilisateur else '',
        'actif': professeur.utilisateur.actif if professeur.utilisateur else professeur.actif,
        'enseignement_ids': [enseignement.id for enseignement in enseignements],
        'affectations': [{
            'id': enseignement.id,
            'classe': enseignement.classe.nom,
            'matiere': enseignement.matiere.nom,
        } for enseignement in enseignements],
    }


@api_view(['GET'])
@require_admin
def professeurs_list_view(request):
    annee = get_annee_courante()
    professeurs = Professeur.objects.select_related('utilisateur').order_by('nom', 'prenom')
    return Response({'professeurs': [_professeur_data(p, annee) for p in professeurs]})


@api_view(['POST'])
@require_admin
def professeurs_save_view(request, professeur_id=None):
    prenom = str(request.data.get('prenom', '')).strip()
    nom = str(request.data.get('nom', '')).strip()
    username = str(request.data.get('username', '')).strip()
    password = request.data.get('password', '')
    enseignement_ids = request.data.get('enseignement_ids')
    if not prenom or not nom or not username:
        return Response({'error': 'Le nom, le prénom et l’identifiant sont obligatoires'}, status=400)
    if not isinstance(enseignement_ids, list) or not enseignement_ids:
        return Response({'error': 'Affectez au moins une matière et une classe'}, status=400)
    try:
        ids = [int(value) for value in enseignement_ids]
    except (TypeError, ValueError):
        return Response({'error': 'Sélection d’affectations invalide'}, status=400)
    if len(ids) != len(set(ids)):
        return Response({'error': 'Une affectation ne peut être sélectionnée qu’une seule fois'}, status=400)
    if professeur_id is None and (not isinstance(password, str) or len(password) < 6):
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères'}, status=400)
    if (password and (not isinstance(password, str) or len(password) < 6)):
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères'}, status=400)

    annee = get_annee_courante()
    if not annee:
        return Response({'error': 'Aucune année scolaire active'}, status=400)

    professeur = None
    if professeur_id is not None:
        professeur = Professeur.objects.select_related('utilisateur').filter(
            id=professeur_id,
        ).first()
        if not professeur:
            return Response({'error': 'Professeur introuvable'}, status=404)
        if not professeur.utilisateur_id and (not isinstance(password, str) or len(password) < 6):
            return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères'}, status=400)
        existing_usernames = Utilisateur.objects.filter(username=username)
        if professeur.utilisateur_id:
            existing_usernames = existing_usernames.exclude(id=professeur.utilisateur_id)
        if existing_usernames.exists():
            return Response({'error': 'Cet identifiant est déjà utilisé'}, status=409)
    elif Utilisateur.objects.filter(username=username).exists():
        return Response({'error': 'Cet identifiant est déjà utilisé'}, status=409)

    enseignements = list(Enseignement.objects.filter(id__in=ids, annee=annee))
    if len(enseignements) != len(ids):
        return Response({'error': 'Une ou plusieurs affectations sont introuvables pour l’année active'}, status=400)
    if any(e.professeur_id not in (None, professeur.id if professeur else None) for e in enseignements):
        return Response({'error': 'Une affectation est déjà attribuée à un autre professeur'}, status=409)

    try:
        with transaction.atomic():
            if professeur_id is None:
                utilisateur = Utilisateur.objects.create(
                    prenom=prenom, nom=nom, username=username,
                    password=hash_password(password), role='professeur', actif=True,
                )
                professeur = Professeur.objects.create(
                    utilisateur=utilisateur, prenom=prenom, nom=nom, actif=True,
                )
            else:
                utilisateur = professeur.utilisateur
                if not utilisateur:
                    utilisateur = Utilisateur(
                        role='professeur', actif=professeur.actif,
                    )
                utilisateur.prenom = prenom
                utilisateur.nom = nom
                utilisateur.username = username
                if password:
                    utilisateur.password = hash_password(password)
                utilisateur.save()
                if not professeur.utilisateur_id:
                    professeur.utilisateur = utilisateur
                    professeur.save(update_fields=['utilisateur'])
                professeur.prenom = prenom
                professeur.nom = nom
                professeur.save(update_fields=['prenom', 'nom'])

            for enseignement in Enseignement.objects.filter(
                professeur=professeur, annee=annee
            ).exclude(id__in=ids):
                enseignement.professeur = None
                enseignement.save(update_fields=['professeur'])
            for enseignement in Enseignement.objects.filter(id__in=ids):
                if enseignement.professeur_id != professeur.id:
                    enseignement.professeur = professeur
                    enseignement.save(update_fields=['professeur'])
    except IntegrityError:
        return Response({'error': 'Cet identifiant est déjà utilisé'}, status=409)
    return Response({'ok': True, 'professeur_id': professeur.id}, status=201 if professeur_id is None else 200)


@api_view(['POST'])
@require_admin
def professeurs_toggle_view(request, professeur_id):
    professeur = Professeur.objects.select_related('utilisateur').filter(
        id=professeur_id, utilisateur__isnull=False,
    ).first()
    if not professeur:
        return Response({'error': 'Professeur introuvable'}, status=404)
    professeur.utilisateur.actif = not professeur.utilisateur.actif
    professeur.utilisateur.save(update_fields=['actif'])
    professeur.actif = professeur.utilisateur.actif
    professeur.save(update_fields=['actif'])
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_admin
def professeurs_delete_view(request, professeur_id):
    professeur = Professeur.objects.filter(id=professeur_id, utilisateur__isnull=False).first()
    if not professeur:
        return Response({'error': 'Professeur introuvable'}, status=404)
    professeur.delete()
    return Response({'ok': True})


# ─────────────────────────── AGENTS ───────────────────────────

@api_view(['GET'])
@require_admin
def agents_list_view(request):
    agents = Utilisateur.objects.filter(role='agent').order_by('nom')
    return Response({'agents': UtilisateurSerializer(agents, many=True).data})


@api_view(['POST'])
@require_admin
def agents_add_view(request):
    payload = UtilisateurWriteSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    d = payload.validated_data
    try:
        Utilisateur.objects.create(
            prenom=d['prenom'], nom=d['nom'], username=d['username'],
            password=hash_password(d.get('password') or 'agent123'), role='agent', actif=True,
        )
        return Response({'ok': True})
    except IntegrityError:
        return Response({'error': 'error'}, status=400)


@api_view(['POST', 'PUT'])
@require_admin
def agents_edit_view(request, agent_id):
    agent = Utilisateur.objects.filter(id=agent_id, role='agent').first()
    if not agent:
        return Response({'error': 'not_found'}, status=404)

    payload = UtilisateurWriteSerializer(agent, data=request.data, partial=True)
    payload.is_valid(raise_exception=True)
    d = payload.validated_data
    agent.prenom = d.get('prenom', agent.prenom)
    agent.nom = d.get('nom', agent.nom)
    agent.username = d.get('username', agent.username)
    if d.get('password'):
        agent.password = hash_password(d['password'])
    agent.save()
    return Response({'ok': True})


@api_view(['POST'])
@require_admin
def agents_toggle_view(request, agent_id):
    agent = Utilisateur.objects.filter(id=agent_id).first()
    if agent:
        agent.actif = not agent.actif
        agent.save()
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_admin
def agents_delete_view(request, agent_id):
    Utilisateur.objects.filter(id=agent_id, role='agent').delete()
    return Response({'ok': True})


# ─────────────────────────── CLASSES ───────────────────────────

@api_view(['GET'])
@require_admin
def classes_list_view(request):
    classes = Classe.objects.order_by('niveau', 'nom')
    return Response({'classes': ClasseSerializer(classes, many=True).data})


@api_view(['POST'])
@require_admin
def classes_add_view(request):
    payload = ClasseWriteSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    payload.save()
    return Response({'ok': True})


@api_view(['POST', 'PUT'])
@require_admin
def classes_edit_view(request, classe_id):
    classe = Classe.objects.filter(id=classe_id).first()
    if not classe:
        return Response({'error': 'not_found'}, status=404)
    payload = ClasseWriteSerializer(classe, data=request.data)
    payload.is_valid(raise_exception=True)
    payload.save()
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_admin
def classes_delete_view(request, classe_id):
    Classe.objects.filter(id=classe_id).delete()
    return Response({'ok': True})


# ─────────────────────────── ANNÉES ───────────────────────────

@api_view(['GET'])
@require_admin
def annees_list_view(request):
    annees = []
    for a in AnneeScolaire.objects.order_by('-id'):
        annees.append({
            'id': a.id, 'libelle': a.libelle, 'courante': a.courante, 'debut': a.debut,
            'nb_eleves': a.eleve_set.count(),
            'total_entrees': Entree.objects.filter(annee=a).aggregate(t=Sum('montant'))['t'] or 0,
            'total_sorties': Sortie.objects.filter(annee=a).aggregate(t=Sum('montant'))['t'] or 0,
        })
    return Response({'annees': AnneeScolaireStatsSerializer(annees, many=True).data})


@api_view(['POST'])
@require_admin
def annees_add_view(request):
    payload = AnneeScolaireAddSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            annee_precedente = get_annee_courante()
            AnneeScolaire.objects.filter(courante=True).update(courante=False)
            nouvelle_annee = AnneeScolaire.objects.create(
                libelle=payload.validated_data['libelle'], courante=True,
            )
            if annee_precedente:
                anciens_enseignements = Enseignement.objects.filter(
                    annee=annee_precedente,
                ).select_related('matiere')
                Enseignement.objects.bulk_create([
                    Enseignement(
                        classe=enseignement.classe,
                        matiere=enseignement.matiere,
                        professeur=enseignement.professeur,
                        annee=nouvelle_annee,
                        coefficient=enseignement.get_coefficient(),
                    )
                    for enseignement in anciens_enseignements
                ])
        return Response({'ok': True})
    except IntegrityError:
        return Response({'error': 'error'}, status=400)


@api_view(['POST'])
@require_admin
def annees_switch_view(request, annee_id):
    for annee in AnneeScolaire.objects.filter(courante=True).exclude(id=annee_id):
        annee.courante = False
        annee.save(update_fields=['courante'])
    annee = AnneeScolaire.objects.filter(id=annee_id).first()
    if annee and not annee.courante:
        annee.courante = True
        annee.save(update_fields=['courante'])
    return Response({'ok': True})


@api_view(['DELETE', 'POST'])
@require_admin
def annees_delete_view(request, annee_id):
    annee = AnneeScolaire.objects.filter(id=annee_id).first()
    if annee and annee.courante:
        return Response({'error': 'error_delete_current'}, status=400)
    try:
        AnneeScolaire.objects.filter(id=annee_id).delete()
        return Response({'ok': True})
    except Exception:
        return Response({'error': 'error_integrity'}, status=400)


# ─────────────────────────── STATS ───────────────────────────

@api_view(['GET'])
@require_admin
def stats_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'annee': None, 'byType': [], 'byClasse': [], 'byMois': []})

    by_type = list(Entree.objects.filter(annee=annee).values('type').annotate(total=Sum('montant')))
    by_classe = list(Entree.objects.filter(annee=annee, classe_nom__isnull=False)
                      .values('classe_nom').annotate(total=Sum('montant')).order_by('-total')[:10])
    by_mois = list(Entree.objects.filter(annee=annee, type='ecolage', mois_index__isnull=False)
                    .values('mois_index').annotate(total=Sum('montant')).order_by('mois_index'))

    from .serializers import AnneeScolaireSerializer
    return Response({'annee': AnneeScolaireSerializer(annee).data,
                      'byType': by_type, 'byClasse': by_classe, 'byMois': by_mois})
