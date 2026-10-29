from django.db import models


class Utilisateur(models.Model):
    ROLE_CHOICES = (('admin', 'admin'), ('agent', 'agent'), ('professeur', 'professeur'))
    prenom = models.CharField(max_length=150)
    nom = models.CharField(max_length=150)
    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=255)  # hash bcrypt
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'
        ordering = ['nom']

    def __str__(self):
        return f'{self.prenom} {self.nom}'


class AnneeScolaire(models.Model):
    libelle = models.CharField(max_length=20, unique=True)
    courante = models.BooleanField(default=False)
    debut = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'annees_scolaires'

    def __str__(self):
        return self.libelle


class Classe(models.Model):
    nom = models.CharField(max_length=100)
    niveau = models.CharField(max_length=100)
    tarif_inscription = models.IntegerField(default=0)
    tarif_ecolage = models.IntegerField(default=0)
    tarif_fascicule = models.IntegerField(default=0)
    tarif_location = models.IntegerField(default=0)

    class Meta:
        db_table = 'classes'
        ordering = ['niveau', 'nom']

    def __str__(self):
        return self.nom


class Eleve(models.Model):
    numero = models.CharField(max_length=50)
    prenom = models.CharField(max_length=150)
    nom = models.CharField(max_length=150)
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, db_column='classe_id')
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    fascicule_paye = models.BooleanField(default=False)
    location_payee = models.BooleanField(default=False)
    date_inscription = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eleves'
        ordering = ['nom', 'prenom']

    def __str__(self):
        return f'{self.nom} {self.prenom}'


class MoisEcolage(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, db_column='eleve_id')
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    mois_index = models.IntegerField()
    date_paiement = models.CharField(max_length=20, null=True, blank=True)
    type_paiement_id = models.IntegerField(default=0)

    class Meta:
        db_table = 'mois_ecolage'
        unique_together = ('eleve', 'annee', 'mois_index', 'type_paiement_id')


class TypePaiement(models.Model):
    nom = models.CharField(max_length=150, unique=True)
    description = models.TextField(null=True, blank=True)
    categorie = models.CharField(max_length=20, default='autre')  # mensuel, annuel, autre
    montant = models.IntegerField(default=0)
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'types_paiement'

    def __str__(self):
        return self.nom


class Entree(models.Model):
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    numero = models.CharField(max_length=50, null=True, blank=True)
    date = models.CharField(max_length=20)
    type = models.CharField(max_length=50)
    eleve_nom = models.CharField(max_length=255, null=True, blank=True)
    classe_nom = models.CharField(max_length=100, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    montant = models.IntegerField()
    mois_index = models.IntegerField(null=True, blank=True)
    agent = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, db_column='agent_id')
    eleve = models.ForeignKey(Eleve, on_delete=models.SET_NULL, null=True, blank=True, db_column='eleve_id')
    classe = models.ForeignKey(Classe, on_delete=models.SET_NULL, null=True, blank=True, db_column='classe_id')
    type_paiement_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'entrees'
        ordering = ['-created_at']


class Parametre(models.Model):
    cle = models.CharField(max_length=100, primary_key=True)
    valeur = models.TextField(default='')

    class Meta:
        db_table = 'parametres'


class JournalOperation(models.Model):
    ACTION_CHOICES = (
        ('creation', 'Création / enregistrement'),
        ('modification', 'Modification'),
        ('suppression', 'Suppression'),
    )

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, db_column='utilisateur_id'
    )
    nom_utilisateur = models.CharField(max_length=301)
    role_utilisateur = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    objet = models.CharField(max_length=500, blank=True)
    date_operation = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'journal_operations'
        ordering = ['-date_operation', '-id']
        indexes = [
            models.Index(fields=['-date_operation'], name='journal_date_idx'),
            models.Index(fields=['action', '-date_operation'], name='journal_action_date_idx'),
        ]

    def __str__(self):
        return f'{self.nom_utilisateur} {self.get_action_display()} : {self.objet}'


class Sortie(models.Model):
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    numero = models.CharField(max_length=50)
    date = models.CharField(max_length=20)
    motif = models.CharField(max_length=255)
    montant = models.IntegerField()
    agent = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, db_column='agent_id')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sorties'
        ordering = ['-created_at']


class CarnetFacturation(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, db_column='eleve_id')
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.SET_NULL, null=True, blank=True, db_column='annee_id')
    type_paiement = models.ForeignKey(TypePaiement, on_delete=models.CASCADE, db_column='type_paiement_id')
    type = models.CharField(max_length=100, null=True, blank=True)
    mois_index = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='non_paye')
    date_paiement = models.CharField(max_length=20, null=True, blank=True)
    montant = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'carnet_facturation'
        unique_together = ('eleve', 'annee', 'type_paiement')


class LocationBook(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, db_column='eleve_id')
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    num_location = models.CharField(max_length=50, null=True, blank=True)
    quantite = models.IntegerField(default=1)
    montant_unitaire = models.IntegerField()
    montant_total = models.IntegerField()
    date_location = models.CharField(max_length=30, null=True, blank=True)
    agent = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, db_column='agent_id')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'location_books'
        ordering = ['-created_at']


class LettrePdf(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, db_column='eleve_id')
    type = models.CharField(max_length=50)
    date_generation = models.DateTimeField(auto_now_add=True)
    contenu = models.TextField(null=True, blank=True)
    agent = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, db_column='agent_id')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lettres_pdf'
        
class Presence(models.Model):
    PERIODE_CHOICES = (('matin', 'matin'), ('soir', 'soir'))
    STATUT_CHOICES = (('present', 'present'), ('absent', 'absent'), ('retard', 'retard'))

    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, db_column='eleve_id')
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, db_column='classe_id')
    periode = models.CharField(max_length=10, choices=PERIODE_CHOICES)
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES)
    date_presence = models.CharField(max_length=20)  # YYYY-MM-DD
    agent = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, blank=True, db_column='agent_id')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'presences'
        unique_together = ('eleve', 'annee', 'date_presence', 'periode')
        ordering = ['-date_presence', 'periode']

    def __str__(self):
        return f'{self.eleve} {self.date_presence} {self.periode} {self.statut}'


class Professeur(models.Model):
    utilisateur = models.OneToOneField(
        Utilisateur, on_delete=models.CASCADE, null=True, blank=True,
        related_name='profil_professeur', db_column='utilisateur_id',
    )
    nom = models.CharField(max_length=150)
    prenom = models.CharField(max_length=150)
    telephone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    actif = models.BooleanField(default=True)
    taux_horaire = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'professeurs'
        ordering = ['nom', 'prenom']

    def __str__(self):
        return f'{self.prenom} {self.nom}'


class PointageProfesseur(models.Model):
    STATUT_CHOICES = (('present', 'present'), ('absent', 'absent'), ('retard', 'retard'))

    professeur = models.ForeignKey(
        Professeur, on_delete=models.CASCADE, related_name='pointages', db_column='professeur_id'
    )
    date = models.DateField()
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default='present')
    heure_entree = models.TimeField(null=True, blank=True)
    heure_sortie = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pointages_professeurs'
        constraints = [
            models.UniqueConstraint(
                fields=('professeur', 'date'), name='unique_pointage_professeur_date'
            ),
        ]
        ordering = ['-date', 'professeur__nom', 'professeur__prenom']

    def __str__(self):
        return f'{self.professeur} {self.date}'


class FichePaieProf(models.Model):
    professeur = models.ForeignKey(
        Professeur, on_delete=models.CASCADE, related_name='fiches_paie',
        db_column='professeur_id',
    )
    mois = models.DateField()
    total_heures = models.DecimalField(max_digits=12, decimal_places=6)
    taux_horaire = models.DecimalField(max_digits=10, decimal_places=2)
    montant_total = models.DecimalField(max_digits=12, decimal_places=2)
    est_paye = models.BooleanField(default=False)
    date_paiement = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'fiches_paie_professeurs'
        constraints = [
            models.UniqueConstraint(
                fields=('professeur', 'mois'), name='unique_fiche_paie_prof_mois'
            ),
        ]
        ordering = ['-mois', 'professeur__nom', 'professeur__prenom']

    def __str__(self):
        return f'{self.professeur} {self.mois:%Y-%m}'


class Matiere(models.Model):
    nom = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, null=True, blank=True)
    coefficient_defaut = models.IntegerField(default=1)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'matieres'
        ordering = ['nom']

    def __str__(self):
        return self.nom


class Facture(models.Model):
    STATUT_CHOICES = (
        ('reservee', 'Réservée'),
        ('emise', 'Émise'),
        ('annulee', 'Annulée'),
    )

    numero = models.CharField(max_length=32, unique=True, null=True, blank=True)
    telephone_etablissement = models.CharField(max_length=50, blank=True)
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default='reservee')
    date_emission = models.DateTimeField(null=True, blank=True)
    entree = models.OneToOneField(
        'Entree', on_delete=models.SET_NULL, null=True, blank=True, related_name='facture',
    )
    location_livre = models.OneToOneField(
        'LocationBook', on_delete=models.SET_NULL, null=True, blank=True, related_name='facture',
    )
    fiche_paie = models.OneToOneField(
        'FichePaieProf', on_delete=models.SET_NULL, null=True, blank=True, related_name='facture',
    )

    class Meta:
        db_table = 'factures'
        ordering = ['-id']


class Enseignement(models.Model):
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, db_column='classe_id')
    matiere = models.ForeignKey(Matiere, on_delete=models.CASCADE, db_column='matiere_id')
    professeur = models.ForeignKey(
        Professeur, on_delete=models.SET_NULL, null=True, blank=True, db_column='professeur_id'
    )
    annee = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, db_column='annee_id')
    coefficient = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'enseignements'
        unique_together = ('classe', 'matiere', 'annee')
        ordering = ['matiere__nom']

    def get_coefficient(self):
        if self.coefficient is not None:
            return self.coefficient
        return self.matiere.coefficient_defaut

    def __str__(self):
        return f'{self.matiere.nom} -> {self.classe.nom} (Coef: {self.get_coefficient()})'


class Evaluation(models.Model):
    PERIODE_CHOICES = (
        ('trimestre_1', 'Trimestre 1'),
        ('trimestre_2', 'Trimestre 2'),
        ('trimestre_3', 'Trimestre 3'),
        ('semestre_1', 'Semestre 1'),
        ('semestre_2', 'Semestre 2'),
    )

    enseignement = models.ForeignKey(
        Enseignement, on_delete=models.CASCADE, db_column='enseignement_id'
    )
    titre = models.CharField(max_length=150)
    periode = models.CharField(max_length=30, choices=PERIODE_CHOICES)
    note_sur = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    date_evaluation = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'evaluations'
        ordering = ['periode', 'date_evaluation', 'titre']

    def __str__(self):
        return f'{self.titre} ({self.enseignement.matiere.nom}) - {self.periode}'


class Note(models.Model):
    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, db_column='evaluation_id')
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, db_column='eleve_id')
    valeur = models.DecimalField(max_digits=5, decimal_places=2)
    appreciation = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notes'
        unique_together = ('evaluation', 'eleve')

    def __str__(self):
        return f'{self.eleve.nom} {self.eleve.prenom} : {self.valeur}/{self.evaluation.note_sur}'