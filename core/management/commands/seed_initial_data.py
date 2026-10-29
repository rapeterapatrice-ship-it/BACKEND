from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Utilisateur, AnneeScolaire, Classe, Eleve, Presence, TypePaiement, Parametre
from core.auth import hash_password


class Command(BaseCommand):
    help = "Initialise les données de base (utilisateurs, année scolaire, classes, types de paiement, paramètres)."

    def handle(self, *args, **options):
        if Utilisateur.objects.count() == 0:
            Utilisateur.objects.create(prenom='Admin', nom='Principal', username='admin',
                                        password=hash_password('admin123'), role='admin', actif=True)
            Utilisateur.objects.create(prenom='Marie', nom='Rakoto', username='agent1',
                                        password=hash_password('agent123'), role='agent', actif=True)
            Utilisateur.objects.create(prenom='Jean', nom='Rabe', username='agent2',
                                        password=hash_password('agent456'), role='agent', actif=True)
            self.stdout.write(self.style.SUCCESS('✓ Utilisateurs créés (admin/admin123, agent1/agent123, agent2/agent456)'))

        if AnneeScolaire.objects.count() == 0:
            today = timezone.localdate()
            school_start_year = today.year if today.month >= 9 else today.year - 1
            school_year = f'{school_start_year}-{school_start_year + 1}'
            AnneeScolaire.objects.create(
                libelle=school_year, courante=True, debut=f'{school_start_year}-09-01'
            )
            self.stdout.write(self.style.SUCCESS(f'✓ Année scolaire {school_year} créée'))

        defaults = {
            'nom_etablissement': 'EduFinance', 'theme_couleur': 'green', 'logo_url': '',
            'seuil_leger': '10', 'seuil_modere': '20', 'seuil_grave': '30', 'delai_retard': '0',
        }
        for cle, valeur in defaults.items():
            Parametre.objects.get_or_create(cle=cle, defaults={'valeur': valeur})
        self.stdout.write(self.style.SUCCESS('✓ Paramètres initialisés'))

        if TypePaiement.objects.count() == 0:
            types = [
                ('Activite piscine mensuelle', 'Frais mensuels pour activite piscine', 15000, 'mensuel'),
                ('Activite piscine annuelle', 'Frais annuels pour activite piscine', 150000, 'annuel'),
                ('Fournitures scolaires', 'Fournitures et materiel scolaire', 50000, 'autre'),
                ('Transport', 'Frais de transport', 30000, 'autre'),
            ]
            for nom, desc, montant, cat in types:
                TypePaiement.objects.create(nom=nom, description=desc, montant=montant, actif=True, categorie=cat)
            self.stdout.write(self.style.SUCCESS('✓ Types de paiement créés'))

        if Classe.objects.count() == 0:
            classes = [
                ('Crèche', 'Préscolaire', 50000, 25000, 15000, 10000),
                ('TPS', 'Préscolaire', 55000, 28000, 15000, 10000),
                ('PS', 'Préscolaire', 55000, 28000, 15000, 10000),
                ('MS', 'Préscolaire', 60000, 30000, 15000, 10000),
                ('GS', 'Préscolaire', 60000, 30000, 15000, 10000),
                ('CP', 'Primaire', 75000, 35000, 20000, 12000),
                ('CE1', 'Primaire', 75000, 35000, 20000, 12000),
                ('CE2', 'Primaire', 80000, 38000, 20000, 12000),
                ('CM1', 'Primaire', 80000, 38000, 20000, 12000),
                ('CM2', 'Primaire', 85000, 40000, 20000, 12000),
                ('6ème', 'Collège', 100000, 50000, 25000, 15000),
                ('5ème', 'Collège', 100000, 50000, 25000, 15000),
                ('4ème', 'Collège', 110000, 55000, 25000, 15000),
                ('3ème', 'Collège', 110000, 55000, 25000, 15000),
                ('Seconde', 'Lycée', 130000, 65000, 30000, 18000),
                ('Première S', 'Lycée', 130000, 65000, 30000, 18000),
                ('Première L', 'Lycée', 130000, 65000, 30000, 18000),
                ('Première OSE', 'Lycée', 130000, 65000, 30000, 18000),
                ('Terminale S', 'Lycée', 140000, 70000, 30000, 18000),
                ('Terminale L', 'Lycée', 140000, 70000, 30000, 18000),
                ('Terminale OSE', 'Lycée', 140000, 70000, 30000, 18000),
            ]
            for nom, niveau, ins, eco, fas, loc in classes:
                Classe.objects.create(nom=nom, niveau=niveau, tarif_inscription=ins, tarif_ecolage=eco,
                                       tarif_fascicule=fas, tarif_location=loc)
            self.stdout.write(self.style.SUCCESS('✓ Classes créées'))

        annee = AnneeScolaire.objects.filter(courante=True).first()
        if annee:
            date_presence = timezone.localdate().isoformat()
            prenoms = ('Mialy', 'Andry', 'Tiana')
            noms = ('Rakoto', 'Rabe', 'Randria')
            statuts = ('present', 'absent', 'retard')
            eleves_crees = 0

            for classe in Classe.objects.all():
                for index, (prenom, nom) in enumerate(zip(prenoms, noms), start=1):
                    numero = f'TEST{classe.id}-{index:02d}'
                    eleve, cree = Eleve.objects.get_or_create(
                        numero=numero,
                        annee=annee,
                        defaults={
                            'prenom': prenom,
                            'nom': nom,
                            'classe': classe,
                            'date_inscription': date_presence,
                        },
                    )
                    eleves_crees += int(cree)

                    for periode_index, periode in enumerate(('matin', 'soir')):
                        Presence.objects.update_or_create(
                            eleve=eleve,
                            annee=annee,
                            date_presence=date_presence,
                            periode=periode,
                            defaults={
                                'classe': classe,
                                'statut': statuts[(index - 1 + periode_index) % len(statuts)],
                            },
                        )

            self.stdout.write(self.style.SUCCESS(
                f'✓ Élèves de test créés : {eleves_crees}; présences de test renseignées pour le {date_presence}'
            ))

        self.stdout.write(self.style.SUCCESS('Initialisation terminée.'))
