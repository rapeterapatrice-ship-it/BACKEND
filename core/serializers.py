"""
Couche de SÉRIALISATION (DRF).

Ce module est strictement responsable de la conversion entre les instances de
modèles (core/models.py) et le JSON échangé avec le frontend React, ainsi que
de la validation des données entrantes.

Aucune requête à la base de données ni aucune règle métier ne doit vivre ici :
- les requêtes ORM (filter/annotate/…) restent dans les vues (core/views_*.py)
- les règles métier (calcul des retards, mois facturables…) restent dans
  core/payment_logic.py / core/helpers.py

On distingue deux familles de serializers :
1. Les `ModelSerializer` : reflètent directement un modèle (Agent, Classe,
   Élève, Type de paiement, Entrée, Sortie, Location de livres…).
2. Les `Serializer` "simples" : mettent en forme des structures calculées
   côté serveur qui ne correspondent à aucun modèle unique (statistiques du
   tableau de bord, statut de retard d'un élève, aperçu de facture...), ou
   valident des entrées qui ne créent/modifient pas directement un modèle
   (connexion, changement de mot de passe...).
"""
from rest_framework import serializers

from .models import (
    Utilisateur, AnneeScolaire, Classe, Eleve, MoisEcolage, TypePaiement,
    Entree, Parametre, Sortie, CarnetFacturation, LocationBook, LettrePdf, Presence, Facture,
)


# ─────────────────────────────────────────────────────────────────────────
# 1. MODEL SERIALIZERS — un par modèle
# ─────────────────────────────────────────────────────────────────────────

class UtilisateurSerializer(serializers.ModelSerializer):
    """Représentation publique d'un utilisateur (agent ou admin) — sans le hash du mot de passe."""

    class Meta:
        model = Utilisateur
        fields = ['id', 'prenom', 'nom', 'username', 'role', 'actif']


class UtilisateurWriteSerializer(serializers.ModelSerializer):
    """Création/édition d'un agent. Le mot de passe est géré à part (hash bcrypt, voir core/auth.py)."""
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Utilisateur
        fields = ['id', 'prenom', 'nom', 'username', 'password']


class SessionUserSerializer(serializers.ModelSerializer):
    """Utilisateur courant renvoyé par /auth/me et /auth/login (équivalent req.session.user)."""

    class Meta:
        model = Utilisateur
        fields = ['id', 'prenom', 'nom', 'username', 'role']


class AnneeScolaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnneeScolaire
        fields = ['id', 'libelle', 'courante', 'debut']


class AnneeScolaireStatsSerializer(AnneeScolaireSerializer):
    """Année scolaire enrichie des totaux utilisés par la page Admin > Années."""
    nb_eleves = serializers.IntegerField()
    total_entrees = serializers.IntegerField()
    total_sorties = serializers.IntegerField()

    class Meta(AnneeScolaireSerializer.Meta):
        fields = AnneeScolaireSerializer.Meta.fields + ['nb_eleves', 'total_entrees', 'total_sorties']


class ClasseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classe
        fields = ['id', 'nom', 'niveau', 'tarif_inscription', 'tarif_ecolage', 'tarif_fascicule', 'tarif_location']


class EleveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Eleve
        fields = ['id', 'numero', 'prenom', 'nom', 'classe_id', 'annee_id',
                  'fascicule_paye', 'location_payee', 'date_inscription']


class TypePaiementSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypePaiement
        fields = ['id', 'nom', 'description', 'categorie', 'montant', 'actif']


class EntreeSerializer(serializers.ModelSerializer):
    numero_facture = serializers.SerializerMethodField()
    telephone_etablissement = serializers.SerializerMethodField()

    def get_numero_facture(self, obj):
        try:
            return obj.facture.numero
        except Facture.DoesNotExist:
            return None

    def get_telephone_etablissement(self, obj):
        try:
            return obj.facture.telephone_etablissement
        except Facture.DoesNotExist:
            return ''

    class Meta:
        model = Entree
        fields = ['id', 'numero', 'date', 'type', 'eleve_nom', 'classe_nom',
                  'description', 'montant', 'mois_index', 'numero_facture',
                  'telephone_etablissement']


class SortieSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sortie
        fields = ['id', 'numero', 'date', 'motif', 'montant']


class LocationBookSerializer(serializers.ModelSerializer):
    """Location de livres, avec les informations de l'élève repliées à plat
    (même forme que l'ancien SELECT ... JOIN eleves de l'app d'origine)."""
    prenom = serializers.CharField(source='eleve.prenom', read_only=True)
    nom = serializers.CharField(source='eleve.nom', read_only=True)
    numero = serializers.CharField(source='eleve.numero', read_only=True)
    classe_nom = serializers.CharField(source='eleve.classe.nom', read_only=True)
    numero_facture = serializers.SerializerMethodField()
    telephone_etablissement = serializers.SerializerMethodField()

    def get_numero_facture(self, obj):
        try:
            return obj.facture.numero
        except Facture.DoesNotExist:
            return None

    def get_telephone_etablissement(self, obj):
        try:
            return obj.facture.telephone_etablissement
        except Facture.DoesNotExist:
            return ''

    class Meta:
        model = LocationBook
        fields = ['id', 'num_location', 'quantite', 'montant_unitaire', 'montant_total',
                  'date_location', 'prenom', 'nom', 'numero', 'classe_nom',
                  'numero_facture', 'telephone_etablissement']


class ParametreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parametre
        fields = ['cle', 'valeur']


# ─────────────────────────────────────────────────────────────────────────
# 2. SERIALIZERS DE VALIDATION (entrées ne correspondant pas à un simple CRUD)
# ─────────────────────────────────────────────────────────────────────────

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):
    current = serializers.CharField()
    newpwd = serializers.CharField(min_length=6)
    confirm = serializers.CharField(min_length=6)


class SortieAddSerializer(serializers.Serializer):
    motif = serializers.CharField()
    montant = serializers.IntegerField(min_value=1)


class ClasseWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classe
        fields = ['nom', 'niveau', 'tarif_inscription', 'tarif_ecolage', 'tarif_fascicule', 'tarif_location']


class TypePaiementWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypePaiement
        fields = ['nom', 'description', 'montant', 'categorie']


class AnneeScolaireAddSerializer(serializers.Serializer):
    libelle = serializers.RegexField(r'^\d{4}-\d{4}$')


class LocationLivresApercuSerializer(serializers.Serializer):
    eleve_id = serializers.IntegerField()
    classe_id = serializers.IntegerField()
    quantite = serializers.IntegerField(min_value=1)
    montant_unitaire = serializers.IntegerField(min_value=0)


class SortieOutSerializer(serializers.Serializer):
    """Utilisé pour la réponse de GET /sortie (liste + année courante)."""
    sorties = SortieSerializer(many=True)
    annee = AnneeScolaireSerializer(allow_null=True)


# ─────────────────────────────────────────────────────────────────────────
# 3. SERIALIZERS DE SORTIE POUR DES DONNÉES CALCULÉES (non liées à 1 modèle)
# ─────────────────────────────────────────────────────────────────────────

class DashboardStatsSerializer(serializers.Serializer):
    totalEntrees = serializers.IntegerField()
    totalSorties = serializers.IntegerField()
    solde = serializers.IntegerField()
    nbEleves = serializers.IntegerField()
    nbInscriptions = serializers.IntegerField()
    nbAgents = serializers.IntegerField()
    nbClasses = serializers.IntegerField()
    nbAnnees = serializers.IntegerField()


class NiveauStatSerializer(serializers.Serializer):
    niveau = serializers.CharField()
    nb = serializers.IntegerField()


class DashboardSerializer(serializers.Serializer):
    """Réponse complète de GET /dashboard."""
    stats = DashboardStatsSerializer()
    annee = AnneeScolaireSerializer(allow_null=True)
    recentEntrees = EntreeSerializer(many=True)
    niveaux = NiveauStatSerializer(many=True)


class MoisDetailSerializer(serializers.Serializer):
    """Détail du statut d'un mois d'écolage pour un élève (calculé par payment_logic.calculate_eleve_status)."""
    index = serializers.IntegerField()
    nom = serializers.CharField()
    estPaye = serializers.BooleanField()
    joursRetardBrut = serializers.IntegerField()
    joursRetardEffectif = serializers.IntegerField()
    niveau = serializers.CharField()
    badge = serializers.CharField()
    estLePlusAncien = serializers.BooleanField()


class EleveStatusSerializer(serializers.Serializer):
    """Sortie de payment_logic.calculate_eleve_status()."""
    statutGlobal = serializers.CharField()
    severiteGlobal = serializers.CharField()
    joursRetardGlobal = serializers.IntegerField()
    nbMoisImpayes = serializers.IntegerField()
    nbMoisEnRetard = serializers.IntegerField()
    nbMoisImpayesNonEchus = serializers.IntegerField()
    moisEnRetardNoms = serializers.ListField(child=serializers.CharField())
    moisImpayesNonEchusNoms = serializers.ListField(child=serializers.CharField())
    montantDu = serializers.IntegerField()
    detailsMois = MoisDetailSerializer(many=True)
    plusAncienMois = serializers.CharField(allow_null=True)


class FactureSerializer(serializers.Serializer):
    """Structure du reçu affiché dans la modale d'aperçu / impression (frontend React)."""
    titre = serializers.CharField()
    numero = serializers.CharField(allow_null=True)
    date = serializers.CharField()
    prenom = serializers.CharField()
    nom = serializers.CharField()
    classe = serializers.CharField()
    type = serializers.CharField()
    montant = serializers.IntegerField()
    annee = serializers.CharField()
    etablissement = serializers.CharField()
    logo = serializers.CharField(allow_blank=True)
    telephone = serializers.CharField(allow_blank=True)


class PreviewSerializer(serializers.Serializer):
    """Aperçu en attente de validation, stocké en session (workflow aperçu → modifier → valider)."""
    action = serializers.CharField()
    formData = serializers.DictField()
    saveData = serializers.DictField()
    facture = FactureSerializer()

class PresenceLigneSerializer(serializers.Serializer):
    eleve_id = serializers.IntegerField()
    statut = serializers.ChoiceField(choices=['present', 'absent', 'retard'])


class PresenceEnregistrerSerializer(serializers.Serializer):
    classe_id = serializers.IntegerField()
    date = serializers.RegexField(r'^\d{4}-\d{2}-\d{2}$')
    periode = serializers.ChoiceField(choices=['matin', 'soir'])
    lignes = PresenceLigneSerializer(many=True)