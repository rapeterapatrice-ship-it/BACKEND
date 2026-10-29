from django.db.models import Sum, Count
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Entree, Sortie, Eleve, Utilisateur, Classe, AnneeScolaire
from .serializers import DashboardSerializer
from .helpers import get_annee_courante
from .auth import require_auth


@api_view(['GET'])
@require_auth
def dashboard_view(request):
    annee = get_annee_courante()
    if not annee:
        empty = {'stats': {'totalEntrees': 0, 'totalSorties': 0, 'solde': 0, 'nbEleves': 0,
                            'nbInscriptions': 0, 'nbAgents': 0, 'nbClasses': 0, 'nbAnnees': 0},
                  'annee': None, 'recentEntrees': [], 'niveaux': []}
        return Response(DashboardSerializer(empty).data)

    total_entrees = int(Entree.objects.filter(annee=annee).aggregate(t=Sum('montant'))['t'] or 0)
    total_sorties = int(Sortie.objects.filter(annee=annee).aggregate(t=Sum('montant'))['t'] or 0)
    nb_eleves = Eleve.objects.filter(annee=annee).count()
    nb_inscriptions = Entree.objects.filter(annee=annee, type__in=['inscription', 'reinscription']).count()
    nb_agents = Utilisateur.objects.filter(role='agent', actif=True).count()
    nb_classes = Classe.objects.count()
    nb_annees = AnneeScolaire.objects.count()

    niveaux_qs = (Eleve.objects.filter(annee=annee)
                  .values('classe__niveau')
                  .annotate(nb=Count('id')))
    niveaux = [{'niveau': r['classe__niveau'] or 'Non défini', 'nb': int(r['nb'])} for r in niveaux_qs]

    recent = Entree.objects.filter(annee=annee).order_by('-created_at')[:5]

    data = {
        'stats': {
            'totalEntrees': total_entrees, 'totalSorties': total_sorties,
            'solde': total_entrees - total_sorties, 'nbEleves': nb_eleves,
            'nbInscriptions': nb_inscriptions, 'nbAgents': nb_agents,
            'nbClasses': nb_classes, 'nbAnnees': nb_annees,
        },
        'annee': annee, 'recentEntrees': list(recent), 'niveaux': niveaux,
    }
    return Response(DashboardSerializer(data).data)
