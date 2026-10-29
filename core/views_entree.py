import re
from datetime import datetime

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Eleve, Classe, TypePaiement, MoisEcolage, Entree, CarnetFacturation, AnneeScolaire
from .serializers import EntreeSerializer, ClasseSerializer, TypePaiementSerializer, \
    AnneeScolaireSerializer, PreviewSerializer
from .helpers import get_annee_courante, get_param, today_iso, format_date_fr, is_valid_person_name, \
    next_num_paiement, MOIS_FULL
from .auth import require_auth
from .facturation import annuler_facture_reservee, emettre_facture, reserver_facture

TYPE_LABELS = {'inscription': 'Inscription', 'reinscription': 'Réinscription', 'ecolage': 'Écolage',
               'fascicule': 'Fascicule', 'location': 'Location'}


def _annee_im(annee):
    match = re.match(r'^\s*(\d{4})', annee.libelle or '')
    if match:
        return match.group(1)
    if annee.debut:
        try:
            return datetime.strptime(annee.debut[:10], '%Y-%m-%d').strftime('%Y')
        except ValueError:
            pass
    return datetime.now().strftime('%Y')


def _prochain_im(annee):
    prefixe = _annee_im(annee)
    pattern = re.compile(rf'^{re.escape(prefixe)}-(\d{{4,}})$')
    dernier_numero = 0
    for numero in Eleve.objects.filter(numero__startswith=f'{prefixe}-').values_list('numero', flat=True):
        match = pattern.fullmatch(numero)
        if match:
            dernier_numero = max(dernier_numero, int(match.group(1)))
    return f'{prefixe}-{dernier_numero + 1:04d}'


@api_view(['GET'])
@require_auth
def entree_list_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'entrees': [], 'classes': [], 'types': [], 'preview': None, 'modifier': False})

    entrees = Entree.objects.filter(annee=annee).select_related('facture').order_by('-created_at')
    classes = Classe.objects.all().order_by('niveau', 'nom')
    types = TypePaiement.objects.filter(actif=True).order_by('nom')

    modifier = request.GET.get('modifier') == '1'
    want_preview = request.GET.get('preview') == '1' or modifier
    raw_preview = request.session.get('preview') if want_preview else None
    if not want_preview:
        save_data = (request.session.get('preview') or {}).get('saveData') or {}
        annuler_facture_reservee(save_data.get('facture_id'))
        request.session.pop('preview', None)

    preview = PreviewSerializer(raw_preview).data if raw_preview else None

    return Response({
        'entrees': EntreeSerializer(entrees, many=True).data,
        'classes': ClasseSerializer(classes, many=True).data,
        'types': TypePaiementSerializer(types, many=True).data,
        'preview': preview, 'modifier': modifier,
        'annee': AnneeScolaireSerializer(annee).data,
    })


@api_view(['GET'])
@require_auth
def reinscription_recherche_view(request):
    annee = get_annee_courante()
    query = str(request.query_params.get('im', '')).strip()
    if not annee:
        return Response({'eleves': []})
    if len(query) < 2:
        return Response({'eleves': []})

    historiques = Eleve.objects.filter(
        numero__istartswith=query,
    ).select_related('annee', 'classe').order_by('numero', '-annee_id', '-id')

    resultats = []
    numeros_vus = set()
    for eleve in historiques:
        if eleve.numero in numeros_vus:
            continue
        numeros_vus.add(eleve.numero)
        resultats.append({
            'id': eleve.id,
            'numero': eleve.numero,
            'nom': eleve.nom,
            'prenom': eleve.prenom,
            'classe': eleve.classe.nom,
            'annee': eleve.annee.libelle,
        })
        if len(resultats) == 20:
            break
    return Response({'eleves': resultats})


@api_view(['POST'])
@require_auth
def entree_clear_history_view(request):
    annee = get_annee_courante()
    if not annee:
        return Response({'error': 'Aucune année active'}, status=400)
    Entree.objects.filter(annee=annee).delete()
    return Response({'ok': True})


@api_view(['POST'])
@require_auth
def apercu_inscription_view(request):
    body = request.data
    annee = get_annee_courante()
    classe_id = body.get('classe_id')
    type_ = body.get('type')
    date_inscription = body.get('date_inscription')

    classe = Classe.objects.filter(id=classe_id).first()
    if not classe or not annee:
        return Response({'error': 'Classe ou année scolaire introuvable'}, status=400)
    if type_ not in ('inscription', 'reinscription'):
        return Response({'error': 'Type d’inscription invalide'}, status=400)

    eleve_historique = None
    if type_ == 'reinscription':
        try:
            eleve_historique = Eleve.objects.select_related('classe', 'annee').get(
                id=body.get('eleve_id'),
            )
        except (Eleve.DoesNotExist, TypeError, ValueError):
            return Response({
                'error': 'Sélectionnez un élève déjà inscrit à partir de son IM.',
            }, status=400)
        if (
            eleve_historique.annee_id != annee.id
            and Eleve.objects.filter(numero=eleve_historique.numero, annee=annee).exists()
        ):
            return Response({
                'error': 'Cet élève est déjà inscrit pour l’année scolaire en cours.',
            }, status=400)
        numero = eleve_historique.numero
        prenom, nom = eleve_historique.prenom, eleve_historique.nom
    else:
        prenom = body.get('prenom')
        nom = body.get('nom')
        if not prenom or not nom:
            return Response({'error': 'champs'}, status=400)
        if not is_valid_person_name(prenom) or not is_valid_person_name(nom):
            return Response({'error': 'nomprenom'}, status=400)
        exist = Eleve.objects.filter(
            prenom__iexact=prenom.strip(), nom__iexact=nom.strip(),
            classe_id=classe_id, annee=annee,
        ).exists()
        if exist:
            return Response({'error': 'exist'}, status=400)
        numero = _prochain_im(annee)

    montant = classe.tarif_inscription
    date_ins = date_inscription or today_iso()
    facture = reserver_facture(request)

    preview = {
        'action': 'inscription',
        'formData': {
            'classe_id': int(classe_id), 'type': type_, 'prenom': prenom.strip(), 'nom': nom.strip(),
            'classe_nom': classe.nom, 'niveau': classe.niveau, 'date_inscription': date_ins,
            'eleve_historique_id': eleve_historique.id if eleve_historique else None,
        },
        'saveData': {
            'numero': numero, 'montant': montant, 'annee_id': annee.id,
            'date_inscription': date_ins, 'facture_id': facture.id,
        },
        'facture': {
            'titre': "REÇU D'INSCRIPTION" if type_ == 'inscription' else "REÇU DE RÉINSCRIPTION",
            'numero': facture.numero, 'date': format_date_fr(date_ins), 'prenom': prenom.strip(), 'nom': nom.strip(),
            'classe': f'{classe.nom} ({classe.niveau})',
            'type': 'Inscription' if type_ == 'inscription' else 'Réinscription',
            'montant': montant, 'annee': annee.libelle,
            'etablissement': get_param('nom_etablissement', 'EduFinance'), 'logo': get_param('logo_url', ''),
            'telephone': facture.telephone_etablissement,
        }
    }
    request.session['preview'] = preview
    request.session.save()
    return Response({'preview': PreviewSerializer(preview).data})


@api_view(['POST'])
@require_auth
def apercu_ecolage_view(request):
    body = request.data
    annee = get_annee_courante()
    eleve_id = body.get('eleve_id')
    classe_id = body.get('classe_id')
    mois = body.get('mois') or []
    if isinstance(mois, str):
        mois = [mois]
    date_paiement = body.get('date_paiement')
    type_paiement_id = body.get('type_paiement_id')

    if not eleve_id or not classe_id:
        return Response({'error': 'champs'}, status=400)
    mois_arr = [int(m) for m in mois] if mois else []
    if not mois_arr:
        return Response({'error': 'nomain'}, status=400)

    eleve = Eleve.objects.filter(id=eleve_id).first()
    classe = Classe.objects.filter(id=classe_id).first()
    if not eleve or not classe or not annee:
        return Response({'error': '1'}, status=400)

    type_nom = 'Écolage'
    montant_unitaire = classe.tarif_ecolage
    if type_paiement_id:
        tp = TypePaiement.objects.filter(id=type_paiement_id).first()
        if tp:
            type_nom = tp.nom
            montant_unitaire = tp.montant

    total = len(mois_arr) * montant_unitaire
    mois_noms = ', '.join(MOIS_FULL[i] for i in mois_arr)
    num_pay = next_num_paiement(annee.id)
    date_paiement_final = date_paiement or today_iso()
    facture = reserver_facture(request)

    preview = {
        'action': 'ecolage',
        'formData': {'classe_id': int(classe_id), 'eleve_id': int(eleve_id), 'moisArr': mois_arr,
                     'classe_nom': classe.nom, 'eleve_prenom': eleve.prenom, 'eleve_nom_fam': eleve.nom,
                     'date_paiement': date_paiement_final,
                     'type_paiement_id': int(type_paiement_id) if type_paiement_id else None},
        'saveData': {'eleve_id': int(eleve_id), 'classe_id': int(classe_id), 'moisArr': mois_arr,
                     'total': total, 'moisNoms': mois_noms, 'numPay': num_pay, 'annee_id': annee.id,
                     'date_paiement': date_paiement_final,
                     'type_paiement_id': int(type_paiement_id) if type_paiement_id else None,
                     'facture_id': facture.id},
        'facture': {
            'titre': 'REÇU DE PAIEMENT', 'numero': facture.numero, 'date': format_date_fr(date_paiement_final),
            'prenom': eleve.prenom, 'nom': eleve.nom, 'classe': classe.nom,
            'type': f'{type_nom} — {mois_noms}', 'montant': total, 'annee': annee.libelle,
            'etablissement': get_param('nom_etablissement', 'EduFinance'), 'logo': get_param('logo_url', ''),
            'telephone': facture.telephone_etablissement,
        }
    }
    request.session['preview'] = preview
    request.session.save()
    return Response({'preview': PreviewSerializer(preview).data})


@api_view(['POST'])
@require_auth
def apercu_fascicule_view(request):
    body = request.data
    annee = get_annee_courante()
    eleve_id = body.get('eleve_id')
    classe_id = body.get('classe_id')
    payment_type = body.get('payment_type')
    date_paiement = body.get('date_paiement')

    if not eleve_id or not classe_id:
        return Response({'error': 'champs'}, status=400)

    eleve = Eleve.objects.filter(id=eleve_id).first()
    classe = Classe.objects.filter(id=classe_id).first()
    if not eleve or not classe or not annee:
        return Response({'error': '1'}, status=400)

    montant = classe.tarif_fascicule if payment_type == 'fascicule' else classe.tarif_location
    num_pay = next_num_paiement(annee.id)
    date_paiement_f = date_paiement or today_iso()
    facture = reserver_facture(request)

    preview = {
        'action': 'fascicule',
        'formData': {'classe_id': int(classe_id), 'eleve_id': int(eleve_id), 'payment_type': payment_type,
                     'classe_nom': classe.nom, 'date_paiement': date_paiement_f},
        'saveData': {'eleve_id': int(eleve_id), 'classe_id': int(classe_id), 'payment_type': payment_type,
                     'montant': montant, 'numPay': num_pay, 'annee_id': annee.id, 'date_paiement': date_paiement_f,
                     'facture_id': facture.id},
        'facture': {
            'titre': 'REÇU FASCICULE' if payment_type == 'fascicule' else 'REÇU LOCATION',
            'numero': facture.numero, 'date': format_date_fr(date_paiement_f), 'prenom': eleve.prenom, 'nom': eleve.nom,
            'classe': classe.nom,
            'type': 'Fascicule (annuel)' if payment_type == 'fascicule' else 'Location (annuelle)',
            'montant': montant, 'annee': annee.libelle,
            'etablissement': get_param('nom_etablissement', 'EduFinance'), 'logo': get_param('logo_url', ''),
            'telephone': facture.telephone_etablissement,
        }
    }
    request.session['preview'] = preview
    request.session.save()
    return Response({'preview': PreviewSerializer(preview).data})


@api_view(['POST'])
@require_auth
def apercu_type_paiement_view(request):
    body = request.data
    annee = get_annee_courante()
    eleve_id = body.get('eleve_id')
    classe_id = body.get('classe_id')
    type_paiement_id = body.get('type_paiement_id')
    date_paiement = body.get('date_paiement')
    mois_arr = body.get('moisArr') or []

    if not eleve_id or not classe_id or not type_paiement_id:
        return Response({'error': 'champs'}, status=400)

    eleve = Eleve.objects.filter(id=eleve_id).first()
    classe = Classe.objects.filter(id=classe_id).first()
    type_paiement = TypePaiement.objects.filter(id=type_paiement_id).first()
    if not eleve or not classe or not annee or not type_paiement:
        return Response({'error': '1'}, status=400)

    montant = type_paiement.montant
    num_pay = next_num_paiement(annee.id)
    date_paiement_f = date_paiement or today_iso()
    facture = reserver_facture(request)

    preview = {
        'action': 'type-paiement',
        'formData': {'classe_id': int(classe_id), 'eleve_id': int(eleve_id),
                     'type_paiement_id': int(type_paiement_id), 'classe_nom': classe.nom,
                     'date_paiement': date_paiement_f},
        'saveData': {'eleve_id': int(eleve_id), 'classe_id': int(classe_id),
                     'type_paiement_id': int(type_paiement_id), 'montant': montant, 'numPay': num_pay,
                     'annee_id': annee.id, 'date_paiement': date_paiement_f,
                     'moisArr': [int(m) for m in mois_arr] if mois_arr else [],
                     'facture_id': facture.id},
        'facture': {
            'titre': 'REÇU ' + type_paiement.nom.upper(), 'numero': facture.numero, 'date': format_date_fr(date_paiement_f),
            'prenom': eleve.prenom, 'nom': eleve.nom, 'classe': classe.nom, 'type': type_paiement.nom,
            'montant': montant, 'annee': annee.libelle,
            'etablissement': get_param('nom_etablissement', 'EduFinance'), 'logo': get_param('logo_url', ''),
            'telephone': facture.telephone_etablissement,
        }
    }
    request.session['preview'] = preview
    request.session.save()
    return Response({'preview': PreviewSerializer(preview).data})


@api_view(['POST'])
@require_auth
def entree_modifier_view(request):
    raw_preview = request.session.get('preview')
    return Response({'preview': PreviewSerializer(raw_preview).data if raw_preview else None})


@api_view(['POST'])
@require_auth
def entree_valider_view(request):
    p = request.session.get('preview')
    if not p:
        return Response({'error': '1'}, status=400)

    annee = get_annee_courante()
    if not annee:
        return Response({'error': '1'}, status=400)

    user = request.current_user
    try:
        with transaction.atomic():
            annee = AnneeScolaire.objects.select_for_update().get(id=annee.id)
            action = p['action']
            facture_id = p.get('saveData', {}).get('facture_id')

            if action == 'inscription':
                fd = p['formData']
                sd = p['saveData']
                classe = Classe.objects.get(id=fd['classe_id'])
                if fd.get('type') == 'reinscription':
                    eleve_historique = Eleve.objects.filter(
                        id=fd.get('eleve_historique_id'),
                        numero=sd['numero'],
                    ).first()
                    if not eleve_historique:
                        raise ValueError('L’élève sélectionné par IM est introuvable.')
                    if (
                        eleve_historique.annee_id != annee.id
                        and Eleve.objects.filter(numero=sd['numero'], annee=annee).exists()
                    ):
                        raise ValueError('Cet élève est déjà inscrit pour l’année scolaire en cours.')
                    prenom, nom = eleve_historique.prenom, eleve_historique.nom
                else:
                    prenom, nom = fd['prenom'], fd['nom']
                    if not is_valid_person_name(prenom) or not is_valid_person_name(nom):
                        raise ValueError('Nom ou prénom invalide')
                    expected_prefix = _annee_im(annee)
                    if not re.fullmatch(rf'{re.escape(expected_prefix)}-\d{{4,}}', sd['numero']):
                        raise ValueError('IM invalide. Recommencez l’inscription.')
                    if Eleve.objects.filter(numero=sd['numero']).exists():
                        raise ValueError('Cet IM vient d’être attribué. Recommencez l’inscription.')
                    if Eleve.objects.filter(
                        prenom__iexact=prenom, nom__iexact=nom,
                        classe=classe, annee=annee,
                    ).exists():
                        raise ValueError('Cet élève est déjà inscrit dans cette classe pour cette année.')
                if fd.get('type') == 'reinscription' and eleve_historique.annee_id == annee.id:
                    eleve = eleve_historique
                    eleve.prenom = prenom
                    eleve.nom = nom
                    eleve.classe = classe
                    eleve.date_inscription = sd['date_inscription']
                    eleve.save(update_fields=['prenom', 'nom', 'classe', 'date_inscription'])
                else:
                    eleve = Eleve.objects.create(
                        numero=sd['numero'], prenom=prenom, nom=nom, classe=classe, annee=annee,
                        date_inscription=sd['date_inscription']
                    )
                entree = Entree.objects.create(
                    annee=annee, numero=sd['numero'], date=format_date_fr(sd['date_inscription']),
                    type=fd['type'], eleve_nom=f"{nom} {prenom}", classe_nom=classe.nom,
                    description=f"{'Inscription' if fd['type'] == 'inscription' else 'Réinscription'} - {nom} {prenom} ({classe.nom})",
                    montant=sd['montant'], agent_id=user.id, eleve=eleve, classe=classe,
                )
                emettre_facture(facture_id, entree=entree)

            elif action == 'ecolage':
                sd = p['saveData']
                eleve = Eleve.objects.get(id=sd['eleve_id'])
                classe = Classe.objects.get(id=sd['classe_id'])
                type_paiement_id = sd.get('type_paiement_id') or 0

                mois_nouveaux = 0
                mois_nouv_arr = []
                for m in sd['moisArr']:
                    _, created = MoisEcolage.objects.get_or_create(
                        eleve=eleve, annee=annee, mois_index=m, type_paiement_id=type_paiement_id or 0,
                        defaults={'date_paiement': sd['date_paiement']}
                    )
                    if created:
                        mois_nouveaux += 1
                        mois_nouv_arr.append(m)

                if mois_nouveaux > 0:
                    type_nom = 'Écolage'
                    if type_paiement_id:
                        tp = TypePaiement.objects.filter(id=type_paiement_id).first()
                        if tp:
                            type_nom = tp.nom
                    montant_unitaire = round(sd['total'] / len(sd['moisArr']))
                    total_reel = mois_nouveaux * montant_unitaire
                    mois_noms_reels = ', '.join(MOIS_FULL[i] for i in mois_nouv_arr)
                    type_colonne = type_nom if type_paiement_id else 'ecolage'

                    entree = Entree.objects.create(
                        annee=annee, numero=sd['numPay'], date=format_date_fr(sd['date_paiement']),
                        type=type_colonne, eleve_nom=f"{eleve.nom} {eleve.prenom}", classe_nom=classe.nom,
                        description=f"{type_nom} {mois_noms_reels} — {eleve.nom} {eleve.prenom} ({classe.nom})",
                        montant=total_reel, mois_index=mois_nouv_arr[0], agent_id=user.id,
                        eleve=eleve, classe=classe, type_paiement_id=type_paiement_id or None,
                    )
                    emettre_facture(facture_id, entree=entree)
                else:
                    annuler_facture_reservee(facture_id)

            elif action == 'type-paiement':
                sd = p['saveData']
                eleve = Eleve.objects.get(id=sd['eleve_id'])
                classe = Classe.objects.get(id=sd['classe_id'])
                type_paiement = TypePaiement.objects.get(id=sd['type_paiement_id'])
                paiement_effectue = False

                if type_paiement.categorie == 'mensuel':
                    mois_arr = sd.get('moisArr') or []
                    mois_nouveaux = 0
                    for m in mois_arr:
                        _, created = MoisEcolage.objects.get_or_create(
                            eleve=eleve, annee=annee, mois_index=m, type_paiement_id=type_paiement.id,
                            defaults={'date_paiement': sd['date_paiement']}
                        )
                        if created:
                            mois_nouveaux += 1
                    paiement_effectue = mois_nouveaux > 0
                else:
                    try:
                        _, created = CarnetFacturation.objects.get_or_create(
                            eleve=eleve, annee=annee, type_paiement=type_paiement,
                            defaults={'type': type_paiement.nom, 'status': 'paye',
                                      'date_paiement': sd['date_paiement'], 'montant': sd['montant']}
                        )
                        paiement_effectue = created
                    except Exception:
                        paiement_effectue = False

                if paiement_effectue:
                    entree = Entree.objects.create(
                        annee=annee, numero=sd['numPay'], date=format_date_fr(sd['date_paiement']),
                        type=type_paiement.nom, eleve_nom=f"{eleve.nom} {eleve.prenom}", classe_nom=classe.nom,
                        description=f"{type_paiement.nom} — {eleve.nom} {eleve.prenom}",
                        montant=sd['montant'], agent_id=user.id, eleve=eleve, classe=classe,
                        type_paiement_id=type_paiement.id,
                    )
                    emettre_facture(facture_id, entree=entree)
                else:
                    annuler_facture_reservee(facture_id)

            elif action == 'fascicule':
                sd = p['saveData']
                eleve = Eleve.objects.get(id=sd['eleve_id'])
                classe = Classe.objects.get(id=sd['classe_id'])

                if sd['payment_type'] == 'fascicule':
                    eleve.fascicule_paye = True
                else:
                    eleve.location_payee = True
                eleve.save()

                entree = Entree.objects.create(
                    annee=annee, numero=sd['numPay'], date=format_date_fr(sd['date_paiement']),
                    type=sd['payment_type'], eleve_nom=f"{eleve.nom} {eleve.prenom}", classe_nom=classe.nom,
                    description=f"{'Fascicule' if sd['payment_type'] == 'fascicule' else 'Location'} — {eleve.nom} {eleve.prenom}",
                    montant=sd['montant'], agent_id=user.id, eleve=eleve, classe=classe,
                )
                emettre_facture(facture_id, entree=entree)
            else:
                annuler_facture_reservee(facture_id)
    except Exception as e:
        return Response({'error': str(e)}, status=400)

    request.session.pop('preview', None)
    return Response({'ok': True})
