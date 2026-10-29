from django.urls import path

from . import (
    views_auth, views_dashboard, views_eleves, views_entree, views_sortie, views_etat,
    views_retards, views_location_livres, views_lettres, views_admin, views_types_paiement,
    views_parametres, views_misc, views_presences, views_notes, views_pointages, views_journal,
    views_salaires,
    views_site,
)

urlpatterns = [
    # ── Auth ──
    path('auth/login', views_auth.login_view),
    path('auth/logout', views_auth.logout_view),
    path('auth/me', views_auth.me_view),
    path('auth/change-password', views_auth.change_password_view),

    # ── Site public ──
    path('site-web', views_site.site_web_public_view),
    path('admin/site-web', views_site.site_web_admin_view),

    # ── Dashboard ──
    path('dashboard', views_dashboard.dashboard_view),

    # ── Élèves ──
    path('eleves', views_eleves.eleves_list_view),
    path('eleves/export', views_eleves.eleves_export_view),
    path('eleves/<int:eleve_id>', views_eleves.eleve_delete_view),

    # ── Entrées (wizard) ──
    path('entree', views_entree.entree_list_view),
    path('entree/clear-history', views_entree.entree_clear_history_view),
    path('entree/apercu/inscription', views_entree.apercu_inscription_view),
    path('entree/reinscription/rechercher', views_entree.reinscription_recherche_view),
    path('entree/apercu/ecolage', views_entree.apercu_ecolage_view),
    path('entree/apercu/fascicule', views_entree.apercu_fascicule_view),
    path('entree/apercu/type-paiement', views_entree.apercu_type_paiement_view),
    path('entree/modifier', views_entree.entree_modifier_view),
    path('entree/valider', views_entree.entree_valider_view),

    # ── Sorties ──
    path('sortie', views_sortie.sortie_list_view),
    path('sortie/add', views_sortie.sortie_add_view),
    path('sortie/<int:sortie_id>', views_sortie.sortie_delete_view),

    # ── État de compte ──
    path('etat', views_etat.etat_view),

    # ── Retards ──
    path('retards/mois-impayes', views_retards.mois_impayes_view),
    path('retards/en-retard', views_retards.en_retard_view),
    path('retards/recherche', views_retards.retards_recherche_view),
    path('retards/detail/<int:eleve_id>', views_retards.retard_detail_view),

    # ── Lettres ──
    path('lettres-pdf/generer-notification', views_lettres.generer_notification_view),
    path('lettres-pdf/generer-avertissement', views_lettres.generer_avertissement_view),
    path('lettres-pdf/generer-suspension', views_lettres.generer_suspension_view),

    # ── Location de livres ──
    path('location-livres', views_location_livres.location_livres_list_view),
    path('location-livres/apercu', views_location_livres.location_livres_apercu_view),
    path('location-livres/valider', views_location_livres.location_livres_valider_view),
    path('location-livres/<int:location_id>', views_location_livres.location_livres_delete_view),

    # ── Admin : agents ──
    path('admin/agents', views_admin.agents_list_view),
    path('admin/agents/add', views_admin.agents_add_view),
    path('admin/agents/<int:agent_id>/edit', views_admin.agents_edit_view),
    path('admin/agents/<int:agent_id>/toggle', views_admin.agents_toggle_view),
    path('admin/agents/<int:agent_id>', views_admin.agents_delete_view),
    path('admin/professeurs', views_admin.professeurs_list_view),
    path('admin/professeurs/add', views_admin.professeurs_save_view),
    path('admin/professeurs/<int:professeur_id>/edit', views_admin.professeurs_save_view),
    path('admin/professeurs/<int:professeur_id>/toggle', views_admin.professeurs_toggle_view),
    path('admin/professeurs/<int:professeur_id>', views_admin.professeurs_delete_view),

    # ── Admin : classes ──
    path('admin/classes', views_admin.classes_list_view),
    path('admin/classes/add', views_admin.classes_add_view),
    path('admin/classes/<int:classe_id>/edit', views_admin.classes_edit_view),
    path('admin/classes/<int:classe_id>', views_admin.classes_delete_view),

    # ── Admin : années ──
    path('admin/annees', views_admin.annees_list_view),
    path('admin/annees/add', views_admin.annees_add_view),
    path('admin/annees/<int:annee_id>/switch', views_admin.annees_switch_view),
    path('admin/annees/<int:annee_id>', views_admin.annees_delete_view),

    # ── Admin : stats ──
    path('admin/stats', views_admin.stats_view),
    path('admin/journal', views_journal.journal_operations_view),

    # ── Admin : types de paiement ──
    path('admin/types-paiement', views_types_paiement.types_paiement_list_view),
    path('admin/types-paiement/add', views_types_paiement.types_paiement_add_view),
    path('admin/types-paiement/<int:type_id>/edit', views_types_paiement.types_paiement_edit_view),
    path('admin/types-paiement/<int:type_id>/toggle', views_types_paiement.types_paiement_toggle_view),
    path('admin/types-paiement/<int:type_id>', views_types_paiement.types_paiement_delete_view),

    # ── Admin : paramètres ──
    path('admin/parametres', views_parametres.parametres_view),
    path('admin/parametres/nom', views_parametres.parametres_nom_view),
    path('admin/parametres/telephone', views_parametres.parametres_telephone_view),
    path('admin/parametres/theme', views_parametres.parametres_theme_view),
    path('admin/parametres/logo', views_parametres.parametres_logo_view),
    path('admin/parametres/logo/delete', views_parametres.parametres_logo_delete_view),
    path('admin/parametres/retards', views_parametres.parametres_retards_view),
    path('admin/parametres/retards/update', views_parametres.parametres_retards_update_view),

        # ── Présences ──
    path('presences/feuille', views_presences.feuille_view),
    path('presences/enregistrer', views_presences.enregistrer_view),
    path('presences/grille', views_presences.grille_view),

    # ── Pointage des professeurs ──
    path('pointages/feuille', views_pointages.feuille_pointages_view),
    path('pointages/enregistrer', views_pointages.enregistrer_pointage_view),
    path('admin/pointages', views_pointages.feuille_pointages_view),

    # ── Salaires des professeurs ──
    path('admin/salaires-professeurs', views_salaires.salaires_professeurs_view),
    path('admin/salaires-professeurs/<int:professeur_id>/taux', views_salaires.taux_horaire_professeur_view),
    path('admin/salaires-professeurs/<int:professeur_id>/payer', views_salaires.payer_salaire_professeur_view),

    # ── Notes et bulletins ──
    path('academique/contexte', views_notes.contexte_notes_view),
    path('academique/configuration', views_notes.configuration_notes_view),
    path('academique/eleves', views_notes.rechercher_eleves_notes_view),
    path('academique/notes', views_notes.enregistrer_note_view),
    path('academique/bulletin', views_notes.bulletin_eleve_view),
    
    # ── Endpoints utilitaires (ex api.js) ──
    path('misc/eleves-by-classe/<int:classe_id>', views_misc.eleves_by_classe_view),
    path('misc/mois-eleve/<int:eleve_id>', views_misc.mois_eleve_view),
    path('misc/classe/<int:classe_id>', views_misc.classe_detail_view),
    path('misc/eleve/<int:eleve_id>', views_misc.eleve_detail_view),
    path('misc/mois-facturables/<int:eleve_id>', views_misc.mois_facturables_view),
    path('misc/types-paiement', views_misc.types_paiement_actifs_view),
    path('misc/annee-courante', views_misc.annee_courante_view),
]
