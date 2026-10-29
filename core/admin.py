from django.contrib import admin

from .models import Enseignement, Evaluation, Matiere, Note, Professeur


@admin.register(Professeur)
class ProfesseurAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'telephone', 'email', 'actif')
    search_fields = ('nom', 'prenom', 'email')
    list_filter = ('actif',)


@admin.register(Matiere)
class MatiereAdmin(admin.ModelAdmin):
    list_display = ('nom', 'code', 'coefficient_defaut')
    search_fields = ('nom', 'code')


@admin.register(Enseignement)
class EnseignementAdmin(admin.ModelAdmin):
    list_display = ('classe', 'matiere', 'annee', 'professeur', 'coefficient')
    list_filter = ('annee', 'classe')
    search_fields = ('classe__nom', 'matiere__nom', 'professeur__nom')


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ('titre', 'enseignement', 'periode', 'note_sur', 'date_evaluation')
    list_filter = ('periode', 'enseignement__annee')
    search_fields = ('titre', 'enseignement__matiere__nom', 'enseignement__classe__nom')


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('eleve', 'evaluation', 'valeur', 'created_at')
    list_filter = ('evaluation__periode', 'evaluation__enseignement__annee')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__numero', 'evaluation__titre')
