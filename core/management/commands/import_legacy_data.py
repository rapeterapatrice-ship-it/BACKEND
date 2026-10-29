import os
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import (
    Utilisateur, AnneeScolaire, Classe, Eleve, MoisEcolage, TypePaiement,
    Entree, Parametre, Sortie, CarnetFacturation, LocationBook, LettrePdf,
)


def rows(cur, table):
    cur.execute(f'SELECT * FROM {table}')
    cols = [d[0] for d in cur.description]
    for r in cur.fetchall():
        yield dict(zip(cols, r))


class Command(BaseCommand):
    help = "Importe les données de l'ancienne base SQLite (data/edufinance.db) vers Django."

    def add_arguments(self, parser):
        parser.add_argument('--path', type=str, default=None,
                             help="Chemin vers l'ancien fichier edufinance.db")

    def handle(self, *args, **options):
        path = options['path'] or os.path.join(settings.BASE_DIR, 'legacy_data', 'edufinance.db')
        if not os.path.exists(path):
            raise CommandError(f"Fichier introuvable : {path}")

        con = sqlite3.connect(path)
        cur = con.cursor()

        # ── Utilisateurs (hash bcrypt conservé tel quel) ──
        n = 0
        for r in rows(cur, 'users'):
            _, created = Utilisateur.objects.update_or_create(
                id=r['id'], defaults=dict(
                    prenom=r['prenom'], nom=r['nom'], username=r['username'],
                    password=r['password'], role=r['role'], actif=bool(r['actif']),
                ))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} utilisateurs importés'))

        # ── Années scolaires ──
        n = 0
        for r in rows(cur, 'annees_scolaires'):
            AnneeScolaire.objects.update_or_create(
                id=r['id'], defaults=dict(libelle=r['libelle'], courante=bool(r['courante']),
                                           debut=r.get('debut')))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} années scolaires importées'))

        # ── Classes ──
        n = 0
        for r in rows(cur, 'classes'):
            Classe.objects.update_or_create(
                id=r['id'], defaults=dict(
                    nom=r['nom'], niveau=r['niveau'], tarif_inscription=r['tarif_inscription'] or 0,
                    tarif_ecolage=r['tarif_ecolage'] or 0, tarif_fascicule=r['tarif_fascicule'] or 0,
                    tarif_location=r['tarif_location'] or 0))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} classes importées'))

        # ── Types de paiement ──
        n = 0
        for r in rows(cur, 'types_paiement'):
            TypePaiement.objects.update_or_create(
                id=r['id'], defaults=dict(
                    nom=r['nom'], description=r.get('description'), categorie=r.get('categorie') or 'autre',
                    montant=r['montant'] or 0, actif=bool(r['actif'])))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} types de paiement importés'))

        # ── Paramètres ──
        n = 0
        for r in rows(cur, 'parametres'):
            valeur = r['valeur']
            if r['cle'] == 'logo_url' and valeur and valeur.startswith('/uploads/'):
                valeur = '/media' + valeur  # ré-aligne avec MEDIA_URL Django
            Parametre.objects.update_or_create(cle=r['cle'], defaults=dict(valeur=valeur))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} paramètres importés'))

        # ── Élèves ──
        n = 0
        for r in rows(cur, 'eleves'):
            try:
                Eleve.objects.update_or_create(
                    id=r['id'], defaults=dict(
                        numero=r['numero'], prenom=r['prenom'], nom=r['nom'],
                        classe_id=r['classe_id'], annee_id=r['annee_id'],
                        fascicule_paye=bool(r['fascicule_paye']), location_payee=bool(r['location_payee']),
                        date_inscription=r.get('date_inscription')))
                n += 1
            except Exception as e:
                self.stderr.write(f"  élève id={r['id']} ignoré : {e}")
        self.stdout.write(self.style.SUCCESS(f'✓ {n} élèves importés'))

        # ── Mois écolage ──
        n = 0
        for r in rows(cur, 'mois_ecolage'):
            try:
                MoisEcolage.objects.update_or_create(
                    id=r['id'], defaults=dict(
                        eleve_id=r['eleve_id'], annee_id=r['annee_id'], mois_index=r['mois_index'],
                        date_paiement=r.get('date_paiement'), type_paiement_id=r.get('type_paiement_id') or 0))
                n += 1
            except Exception as e:
                self.stderr.write(f"  mois_ecolage id={r['id']} ignoré : {e}")
        self.stdout.write(self.style.SUCCESS(f'✓ {n} lignes mois_ecolage importées'))

        # ── Entrées ──
        n = 0
        for r in rows(cur, 'entrees'):
            try:
                Entree.objects.update_or_create(
                    id=r['id'], defaults=dict(
                        annee_id=r['annee_id'], numero=r.get('numero'), date=r['date'], type=r['type'],
                        eleve_nom=r.get('eleve_nom'), classe_nom=r.get('classe_nom'),
                        description=r.get('description'), montant=r['montant'], mois_index=r.get('mois_index'),
                        agent_id=r.get('agent_id'), eleve_id=r.get('eleve_id'), classe_id=r.get('classe_id'),
                        type_paiement_id=r.get('type_paiement_id')))
                n += 1
            except Exception as e:
                self.stderr.write(f"  entree id={r['id']} ignorée : {e}")
        self.stdout.write(self.style.SUCCESS(f'✓ {n} entrées importées'))

        # ── Sorties ──
        n = 0
        for r in rows(cur, 'sorties'):
            Sortie.objects.update_or_create(
                id=r['id'], defaults=dict(annee_id=r['annee_id'], numero=r['numero'], date=r['date'],
                                           motif=r['motif'], montant=r['montant'], agent_id=r.get('agent_id')))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} sorties importées'))

        # ── Carnet de facturation ──
        n = 0
        for r in rows(cur, 'carnet_facturation'):
            try:
                CarnetFacturation.objects.update_or_create(
                    id=r['id'], defaults=dict(
                        eleve_id=r['eleve_id'], annee_id=r.get('annee_id'),
                        type_paiement_id=r['type_paiement_id'], type=r.get('type'),
                        mois_index=r.get('mois_index'), status=r['status'],
                        date_paiement=r.get('date_paiement'), montant=r['montant']))
                n += 1
            except Exception as e:
                self.stderr.write(f"  carnet_facturation id={r['id']} ignoré : {e}")
        self.stdout.write(self.style.SUCCESS(f'✓ {n} lignes carnet_facturation importées'))

        # ── Locations de livres ──
        n = 0
        for r in rows(cur, 'location_books'):
            LocationBook.objects.update_or_create(
                id=r['id'], defaults=dict(
                    eleve_id=r['eleve_id'], annee_id=r['annee_id'], num_location=r.get('num_location'),
                    quantite=r['quantite'], montant_unitaire=r['montant_unitaire'],
                    montant_total=r['montant_total'], date_location=r.get('date_location'),
                    agent_id=r.get('agent_id')))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} locations de livres importées'))

        # ── Lettres ──
        n = 0
        for r in rows(cur, 'lettres_pdf'):
            LettrePdf.objects.update_or_create(
                id=r['id'], defaults=dict(eleve_id=r['eleve_id'], type=r['type'],
                                           contenu=r.get('contenu'), agent_id=r.get('agent_id')))
            n += 1
        self.stdout.write(self.style.SUCCESS(f'✓ {n} lettres importées'))

        con.close()
        self.stdout.write(self.style.SUCCESS('Import terminé avec succès.'))
