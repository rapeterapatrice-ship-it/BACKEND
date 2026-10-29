from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Eleve, LettrePdf
from .payment_logic import get_annee_courante, calculate_eleve_status
from .helpers import get_param
from .auth import require_auth


def _generer_lettre(request, type_lettre):
    eleve_id = request.data.get('eleve_id')
    annee = get_annee_courante()
    agent_id = request.current_user.id if getattr(request, 'current_user', None) else None

    eleve = Eleve.objects.select_related('classe').filter(id=eleve_id).first()
    if not eleve:
        return Response({'success': False, 'error': 'Élève non trouvé'})

    status = calculate_eleve_status(eleve, annee, datetime.now())
    nom_etablissement = get_param('nom_etablissement', 'EduFinance')
    date_jour = datetime.now().strftime('%d/%m/%Y')

    titre = ''
    corps = ''

    if type_lettre == 'notification':
        titre = 'RAPPEL DE PAIEMENT'
        lignes = '\n'.join(f"- {m['nom']} ({m['joursRetardBrut']} jours de retard)"
                            for m in status['detailsMois'] if not m['estPaye'])
        corps = (f"Nous avons constaté que le paiement de l'écolage pour les mois suivants n'a pas encore "
                 f"été régularisé :\n{lignes}\n\nStatut global : {status['statutGlobal']} "
                 f"(basé sur le mois de {status['plusAncienMois']})\nMontant total dû : {status['montantDu']} Ar\n\n"
                 f"Nous vous prions de bien vouloir régulariser cette situation dans les plus brefs délais.")
    elif type_lettre == 'avertissement':
        titre = 'AVERTISSEMENT POUR RETARD DE PAIEMENT'
        corps = (f"Malgré nos précédents rappels, votre compte présente toujours un retard important.\n"
                 f"Plus ancien mois impayé : {status['plusAncienMois']} ({status['joursRetardGlobal']} jours de retard effectif)\n"
                 f"Statut : {status['statutGlobal']}\n\n"
                 f"Le maintien de cette situation pourrait entraîner des mesures restrictives concernant l'accès aux cours.")
    elif type_lettre == 'suspension':
        titre = 'AVIS DE SUSPENSION TEMPORAIRE'
        corps = (f"En raison d'un retard de paiement jugé GRAVE ({status['joursRetardGlobal']} jours pour le mois de "
                 f"{status['plusAncienMois']}), nous sommes au regret de vous informer de la suspension temporaire "
                 f"de l'accès aux services scolaires pour l'élève {eleve.prenom} {eleve.nom}.\n\n"
                 f"Cette mesure sera levée dès réception du paiement intégral des arriérés (Total : {status['montantDu']} Ar).")

    corps_html = corps.replace('\n', '<br>')
    contenu = f'''
<div class="letter-print">
    <div class="letter-header">
        <div class="school-name">{nom_etablissement.upper()}</div>
        <div class="letter-date">Fait le : {date_jour}</div>
    </div>
    <div class="letter-object">OBJET : {titre}</div>
    <div class="letter-recipient">
        À l'attention des parents de l'élève <strong>{eleve.prenom} {eleve.nom}</strong><br>
        Classe : {eleve.classe.nom} | N° : {eleve.numero}
    </div>
    <div class="letter-body">
        <p>Madame, Monsieur,</p>
        <p>{corps_html}</p>
        <p>Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées.</p>
    </div>
    <div class="letter-footer">
        La Direction de {nom_etablissement}
    </div>
</div>
    '''

    try:
        LettrePdf.objects.create(eleve=eleve, type=type_lettre, contenu=contenu, agent_id=agent_id)
        return Response({'success': True, 'contenu': contenu})
    except Exception as e:
        return Response({'success': False, 'error': str(e)})


@api_view(['POST'])
@require_auth
def generer_notification_view(request):
    return _generer_lettre(request, 'notification')


@api_view(['POST'])
@require_auth
def generer_avertissement_view(request):
    return _generer_lettre(request, 'avertissement')


@api_view(['POST'])
@require_auth
def generer_suspension_view(request):
    return _generer_lettre(request, 'suspension')
