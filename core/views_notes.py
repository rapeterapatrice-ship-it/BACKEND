from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth import require_auth, require_academic_auth
from .helpers import get_annee_courante
from .models import Classe, Eleve, Enseignement, Evaluation, Matiere, Note, Professeur
from .serializers import ClasseSerializer

PERIODES = dict(Evaluation.PERIODE_CHOICES)


@api_view(['GET'])
@require_academic_auth
def contexte_notes_view(request):
    annee = get_annee_courante()
    utilisateur = request.current_user
    professeur = None
    if utilisateur.role == 'professeur':
        try:
            professeur = utilisateur.profil_professeur
        except Professeur.DoesNotExist:
            pass
    teaching_filter = {}
    if utilisateur.role == 'professeur' and professeur:
        teaching_filter['professeur'] = professeur
    classes = Classe.objects.none() if utilisateur.role == 'professeur' else Classe.objects.all()
    classes = classes.order_by('niveau', 'nom')
    enseignements = Enseignement.objects.none()
    evaluations = Evaluation.objects.none()
    if annee:
        enseignements = Enseignement.objects.filter(annee=annee, **teaching_filter).select_related(
            'classe', 'matiere', 'professeur'
        ).order_by('classe__niveau', 'classe__nom', 'matiere__nom')
        if utilisateur.role == 'professeur' and not professeur:
            enseignements = Enseignement.objects.none()
        evaluations = Evaluation.objects.filter(
            enseignement__annee=annee, **{
                f'enseignement__{key}': value for key, value in teaching_filter.items()
            }
        ).select_related('enseignement', 'enseignement__classe', 'enseignement__matiere')
        if utilisateur.role == 'professeur':
            classes = Classe.objects.filter(
                id__in=enseignements.values_list('classe_id', flat=True)
            ).order_by('niveau', 'nom')

    return Response({
        'annee': {'id': annee.id, 'libelle': annee.libelle} if annee else None,
        'classes': ClasseSerializer(classes, many=True).data,
        'matieres': [
            {'id': m.id, 'nom': m.nom, 'code': m.code, 'coefficient_defaut': m.coefficient_defaut}
            for m in Matiere.objects.filter(id__in=enseignements.values_list('matiere_id', flat=True))
            if utilisateur.role == 'professeur'
        ] if utilisateur.role == 'professeur' else [
            {'id': m.id, 'nom': m.nom, 'code': m.code, 'coefficient_defaut': m.coefficient_defaut}
            for m in Matiere.objects.all()
        ],
        'enseignements': [{
            'id': e.id, 'classe_id': e.classe_id, 'matiere_id': e.matiere_id,
            'matiere': e.matiere.nom, 'professeur': str(e.professeur) if e.professeur else None,
            'professeur_id': e.professeur_id,
            'coefficient': e.coefficient, 'coefficient_applique': e.get_coefficient(),
        } for e in enseignements],
        'evaluations': [{
            'id': e.id, 'enseignement_id': e.enseignement_id,
            'classe_id': e.enseignement.classe_id, 'matiere_id': e.enseignement.matiere_id,
            'titre': e.titre, 'periode': e.periode, 'periode_libelle': e.get_periode_display(),
            'note_sur': str(e.note_sur), 'date_evaluation': e.date_evaluation,
        } for e in evaluations],
    })


@api_view(['POST'])
@require_academic_auth
def configuration_notes_view(request):
    if request.current_user.role == 'agent':
        return Response({'error': 'Seul un administrateur peut configurer les matières et évaluations'}, status=403)

    action = request.data.get('action')
    if request.current_user.role == 'professeur' and action != 'evaluation':
        return Response({'error': 'Les professeurs peuvent uniquement créer des évaluations'}, status=403)
    professeur = None
    if request.current_user.role == 'professeur':
        try:
            professeur = request.current_user.profil_professeur
        except Professeur.DoesNotExist:
            return Response({'error': 'Aucun profil professeur associé à ce compte'}, status=403)
    try:
        with transaction.atomic():
            if action == 'matiere':
                nom = str(request.data.get('nom', '')).strip()
                if not nom:
                    return Response({'error': 'Le nom de la matière est obligatoire'}, status=400)
                try:
                    coefficient = int(request.data.get('coefficient_defaut', 1))
                except (TypeError, ValueError):
                    return Response({'error': 'Coefficient invalide'}, status=400)
                if coefficient < 1:
                    return Response({'error': 'Le coefficient doit être supérieur à zéro'}, status=400)
                matiere_id = request.data.get('matiere_id')
                if matiere_id:
                    matiere = Matiere.objects.get(id=matiere_id)
                    matiere.nom = nom
                    matiere.code = str(request.data.get('code', '')).strip() or None
                    matiere.coefficient_defaut = coefficient
                    matiere.save()
                else:
                    if Matiere.objects.filter(nom=nom).exists():
                        return Response({'error': 'Cette matière existe déjà. Modifiez son coefficient dans la liste.'}, status=409)
                    matiere, _ = Matiere.objects.get_or_create(
                        nom=nom,
                        defaults={'code': str(request.data.get('code', '')).strip() or None,
                                  'coefficient_defaut': coefficient},
                    )
                return Response({'ok': True, 'matiere_id': matiere.id})

            annee = get_annee_courante()
            if not annee:
                return Response({'error': 'Aucune année scolaire active'}, status=400)

            if action == 'enseignement':
                classe = Classe.objects.get(id=request.data.get('classe_id'))
                matiere = Matiere.objects.get(id=request.data.get('matiere_id'))
                coefficient_value = request.data.get('coefficient')
                coefficient = int(coefficient_value) if coefficient_value not in (None, '') else None
                if coefficient is not None and coefficient < 1:
                    return Response({'error': 'Le coefficient doit être supérieur à zéro'}, status=400)
                enseignement, _ = Enseignement.objects.update_or_create(
                    classe=classe, matiere=matiere, annee=annee,
                    defaults={'coefficient': coefficient},
                )
                return Response({'ok': True, 'enseignement_id': enseignement.id})

            if action == 'enseignements':
                matiere = Matiere.objects.get(id=request.data.get('matiere_id'))
                assignments = request.data.get('assignments')
                if not isinstance(assignments, list) or not assignments:
                    return Response({'error': 'Sélectionnez au moins une classe'}, status=400)

                classe_ids = set()
                validated_assignments = []
                for assignment in assignments:
                    if not isinstance(assignment, dict):
                        return Response({'error': 'Association de classe invalide'}, status=400)
                    classe_id = int(assignment.get('classe_id'))
                    if classe_id in classe_ids:
                        return Response({'error': 'Une classe ne peut être sélectionnée qu’une seule fois'}, status=400)
                    classe_ids.add(classe_id)
                    classe = Classe.objects.get(id=classe_id)
                    coefficient_value = assignment.get('coefficient')
                    coefficient = int(coefficient_value) if coefficient_value not in (None, '') else None
                    if coefficient is not None and coefficient < 1:
                        return Response({'error': 'Le coefficient doit être supérieur à zéro'}, status=400)
                    validated_assignments.append((classe, coefficient))

                for classe, coefficient in validated_assignments:
                    Enseignement.objects.update_or_create(
                        classe=classe, matiere=matiere, annee=annee,
                        defaults={'coefficient': coefficient},
                    )
                return Response({'ok': True, 'count': len(validated_assignments)})

            if action == 'evaluation':
                enseignement_ids = request.data.get('enseignement_ids')
                if enseignement_ids is not None:
                    if not isinstance(enseignement_ids, list) or not enseignement_ids:
                        return Response({'error': 'Sélectionnez au moins une classe'}, status=400)
                    ids = [int(enseignement_id) for enseignement_id in enseignement_ids]
                    if len(ids) != len(set(ids)):
                        return Response({'error': 'Une classe ne peut être sélectionnée qu’une seule fois'}, status=400)
                    matiere = Matiere.objects.get(id=request.data.get('matiere_id'))
                    teaching_filter = {'professeur': professeur} if professeur else {}
                    enseignements = list(Enseignement.objects.filter(
                        id__in=ids, annee=annee, matiere=matiere, **teaching_filter,
                    ))
                    if len(enseignements) != len(ids):
                        return Response({'error': 'Une ou plusieurs classes ne sont pas associées à cette matière'}, status=400)
                else:
                    teaching_filter = {'professeur': professeur} if professeur else {}
                    enseignements = [Enseignement.objects.get(
                        id=request.data.get('enseignement_id'), annee=annee, **teaching_filter,
                    )]
                titre = str(request.data.get('titre', '')).strip()
                periode = request.data.get('periode')
                note_sur = Decimal(str(request.data.get('note_sur', 20)))
                if not titre:
                    return Response({'error': "Le titre de l'évaluation est obligatoire"}, status=400)
                if periode not in PERIODES:
                    return Response({'error': 'Période invalide'}, status=400)
                if (
                    not note_sur.is_finite() or note_sur <= 0
                    or note_sur > Decimal('999.99')
                    or note_sur != note_sur.quantize(Decimal('0.01'))
                ):
                    return Response({'error': 'La note maximale doit être supérieure à zéro'}, status=400)
                evaluations = [
                    Evaluation(
                        enseignement=enseignement, titre=titre, periode=periode, note_sur=note_sur,
                        date_evaluation=str(request.data.get('date_evaluation', '')).strip() or None,
                    )
                    for enseignement in enseignements
                ]
                for evaluation in evaluations:
                    evaluation.save()
                if len(evaluations) == 1:
                    return Response({'ok': True, 'evaluation_id': evaluations[0].id}, status=201)
                return Response({
                    'ok': True, 'evaluation_ids': [evaluation.id for evaluation in evaluations],
                    'count': len(evaluations),
                }, status=201)

            return Response({'error': 'Action de configuration invalide'}, status=400)
    except (Classe.DoesNotExist, Matiere.DoesNotExist, Enseignement.DoesNotExist):
        return Response({'error': 'Classe, matière ou enseignement introuvable'}, status=404)
    except (TypeError, ValueError, InvalidOperation):
        return Response({'error': 'Données de configuration invalides'}, status=400)
    except IntegrityError:
        return Response({'error': 'Cette matière est déjà configurée pour la classe'}, status=409)


@api_view(['GET'])
@require_academic_auth
def rechercher_eleves_notes_view(request):
    if request.current_user.role != 'professeur':
        return Response({'error': 'La saisie des notes est réservée aux professeurs'}, status=403)

    annee = get_annee_courante()
    classe_id = request.query_params.get('classe_id')
    evaluation_id = request.query_params.get('evaluation_id')
    terme = str(request.query_params.get('q', '')).strip()
    if not annee or not classe_id or not evaluation_id:
        return Response({'eleves': []})

    evaluation_filter = {}
    if request.current_user.role == 'professeur':
        try:
            professeur = request.current_user.profil_professeur
        except Professeur.DoesNotExist:
            return Response({'error': 'Aucun profil professeur associé à ce compte'}, status=403)
        evaluation_filter['enseignement__professeur'] = professeur

    try:
        evaluation = Evaluation.objects.select_related('enseignement').get(
            id=evaluation_id, enseignement__classe_id=classe_id, enseignement__annee=annee,
            **evaluation_filter,
        )
    except Evaluation.DoesNotExist:
        return Response({'error': 'Évaluation introuvable pour cette classe'}, status=404)

    eleves = Eleve.objects.filter(annee=annee, classe_id=classe_id)
    if terme:
        eleves = eleves.filter(
            Q(nom__icontains=terme) | Q(prenom__icontains=terme) | Q(numero__icontains=terme)
        )
    eleves = eleves.order_by('nom', 'prenom')
    notes = {
        note.eleve_id: note
        for note in Note.objects.filter(evaluation=evaluation, eleve__in=eleves)
    }
    return Response({'eleves': [{
        'id': eleve.id, 'numero': eleve.numero, 'nom': eleve.nom, 'prenom': eleve.prenom,
        'note': str(notes[eleve.id].valeur) if eleve.id in notes else None,
        'appreciation': notes[eleve.id].appreciation if eleve.id in notes else '',
    } for eleve in eleves]})


@api_view(['POST'])
@require_academic_auth
def enregistrer_note_view(request):
    if request.current_user.role != 'professeur':
        return Response({'error': 'La saisie des notes est réservée aux professeurs'}, status=403)

    annee = get_annee_courante()
    if not annee:
        return Response({'error': 'Aucune année scolaire active'}, status=400)
    evaluation_filter = {}
    if request.current_user.role == 'professeur':
        try:
            professeur = request.current_user.profil_professeur
        except Professeur.DoesNotExist:
            return Response({'error': 'Aucun profil professeur associé à ce compte'}, status=403)
        evaluation_filter['enseignement__professeur'] = professeur

    try:
        evaluation = Evaluation.objects.select_related('enseignement').get(
            id=request.data.get('evaluation_id'), enseignement__annee=annee,
            **evaluation_filter,
        )
        eleve = Eleve.objects.get(
            id=request.data.get('eleve_id'), annee=annee,
            classe_id=evaluation.enseignement.classe_id,
        )
        valeur = Decimal(str(request.data.get('valeur')))
    except (Evaluation.DoesNotExist, Eleve.DoesNotExist):
        return Response({'error': 'Élève ou évaluation introuvable pour cette année et cette classe'}, status=404)
    except (TypeError, ValueError, InvalidOperation):
        return Response({'error': 'La note doit être un nombre valide'}, status=400)

    if (
        not valeur.is_finite() or valeur < 0 or valeur > evaluation.note_sur
        or valeur > Decimal('999.99')
        or valeur != valeur.quantize(Decimal('0.01'))
    ):
        return Response({'error': f'La note doit être comprise entre 0 et {evaluation.note_sur}'}, status=400)

    note, created = Note.objects.update_or_create(
        evaluation=evaluation, eleve=eleve,
        defaults={'valeur': valeur, 'appreciation': str(request.data.get('appreciation', '')).strip()},
    )
    return Response({
        'ok': True, 'created': created, 'note': str(note.valeur),
        'eleve_id': eleve.id, 'evaluation_id': evaluation.id,
    })


def _moyenne_ponderee(notes_par_eleve, enseignements):
    total_pondere = Decimal('0')
    total_coefficients = Decimal('0')
    for enseignement in enseignements:
        notes = notes_par_eleve.get(enseignement.id, [])
        if not notes:
            continue
        moyenne = sum(
            (note.valeur * Decimal('20') / note.evaluation.note_sur for note in notes),
            Decimal('0'),
        ) / len(notes)
        coefficient = Decimal(enseignement.get_coefficient())
        total_pondere += moyenne * coefficient
        total_coefficients += coefficient
    if not total_coefficients:
        return None
    return total_pondere / total_coefficients


@api_view(['GET'])
@require_auth
def bulletin_eleve_view(request):
    annee = get_annee_courante()
    eleve_id = request.query_params.get('eleve_id')
    periode = request.query_params.get('periode')
    if not annee:
        return Response({'error': 'Aucune année scolaire active'}, status=400)
    if periode not in PERIODES:
        return Response({'error': 'Période invalide'}, status=400)
    try:
        eleve = Eleve.objects.select_related('classe', 'annee').get(id=eleve_id, annee=annee)
    except (Eleve.DoesNotExist, TypeError, ValueError):
        return Response({'error': 'Élève introuvable pour cette année scolaire'}, status=404)

    enseignements = list(Enseignement.objects.filter(
        classe=eleve.classe, annee=annee,
    ).select_related('matiere').order_by('matiere__nom'))
    notes = list(Note.objects.filter(
        evaluation__enseignement__in=enseignements,
        evaluation__periode=periode,
    ).select_related('evaluation', 'evaluation__enseignement').order_by(
        'evaluation__date_evaluation', 'evaluation__titre'
    ))

    notes_by_student = {}
    for note in notes:
        by_subject = notes_by_student.setdefault(note.eleve_id, {})
        by_subject.setdefault(note.evaluation.enseignement_id, []).append(note)

    eleves_classe = list(Eleve.objects.filter(
        classe=eleve.classe, annee=annee
    ).order_by('nom', 'prenom').values('id', 'numero', 'nom', 'prenom'))
    averages = {
        student['id']: _moyenne_ponderee(notes_by_student.get(student['id'], {}), enseignements)
        for student in eleves_classe
    }
    moyenne_eleve = averages.get(eleve.id)
    classes_notes = [average for average in averages.values() if average is not None]
    rang = 1 + sum(average > moyenne_eleve for average in classes_notes) if moyenne_eleve is not None else None

    matieres = []
    for enseignement in enseignements:
        subject_notes = notes_by_student.get(eleve.id, {}).get(enseignement.id, [])
        if subject_notes:
            moyenne = sum(
                (note.valeur * Decimal('20') / note.evaluation.note_sur for note in subject_notes),
                Decimal('0'),
            ) / len(subject_notes)
            appreciations = list(dict.fromkeys(
                note.appreciation.strip() for note in subject_notes
                if note.appreciation and note.appreciation.strip()
            ))
            coefficient = Decimal(enseignement.get_coefficient())
            total_pondere = moyenne * coefficient
        else:
            moyenne = total_pondere = None
            appreciations = []
            coefficient = Decimal(enseignement.get_coefficient())
        matieres.append({
            'matiere': enseignement.matiere.nom,
            'notes': [{
                'evaluation': note.evaluation.titre,
                'valeur': str(note.valeur),
                'note_sur': str(note.evaluation.note_sur),
            } for note in subject_notes],
            'moyenne': round(moyenne, 2) if moyenne is not None else None,
            'coefficient': int(coefficient),
            'total_pondere': round(total_pondere, 2) if total_pondere is not None else None,
            'appreciation': ' / '.join(appreciations),
        })

    return Response({
        'annee': annee.libelle,
        'periode': periode,
        'periode_libelle': PERIODES[periode],
        'etablissement': _nom_etablissement(),
        'eleve': {
            'id': eleve.id, 'numero': eleve.numero, 'nom': eleve.nom,
            'prenom': eleve.prenom, 'classe': eleve.classe.nom, 'niveau': eleve.classe.niveau,
        },
        'matieres': matieres,
        'moyenne_generale': round(moyenne_eleve, 2) if moyenne_eleve is not None else None,
        'rang': rang,
        'effectif_classe': len(classes_notes),
    })


def _nom_etablissement():
    from .models import Parametre
    return Parametre.objects.filter(cle='nom_etablissement').values_list('valeur', flat=True).first() or 'EduFinance'
