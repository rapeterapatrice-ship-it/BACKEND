import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from .audit import reset_audit_actor, set_audit_actor
from .models import (
	AnneeScolaire, Classe, Eleve, Enseignement, Evaluation, Entree, Matiere, MoisEcolage,
	Facture, FichePaieProf, JournalOperation, Note, Parametre, PointageProfesseur, Presence,
	LocationBook, Professeur, TypePaiement,
	Utilisateur,
)
from .payment_logic import calculate_eleve_status, get_mois_facturables


class PresenceViewsTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Test', username='admin-test', password='unused', role='admin'
		)
		self.annee = AnneeScolaire.objects.create(libelle='2026-2027', courante=True)
		self.autre_annee = AnneeScolaire.objects.create(libelle='2025-2026')
		self.classe = Classe.objects.create(nom='CP', niveau='Primaire')
		self.autre_classe = Classe.objects.create(nom='CE1', niveau='Primaire')
		self.eleve = Eleve.objects.create(
			numero='CP-001', prenom='Mialy', nom='Test', classe=self.classe, annee=self.annee
		)
		self.eleve_autre_classe = Eleve.objects.create(
			numero='CE1-001', prenom='Andry', nom='Test', classe=self.autre_classe, annee=self.annee
		)
		self.eleve_autre_annee = Eleve.objects.create(
			numero='CP-OLD', prenom='Tiana', nom='Test', classe=self.classe, annee=self.autre_annee
		)
		session = self.client.session
		session['user_id'] = self.admin.id
		session.save()

	def test_feuille_uses_students_from_selected_class_and_active_year(self):
		response = self.client.get('/api/presences/feuille', {'classe_id': self.classe.id})

		self.assertEqual(response.status_code, 200)
		self.assertEqual([row['eleve_id'] for row in response.json()['eleves']], [self.eleve.id])

	def test_enregistrer_rejects_student_from_another_class(self):
		response = self.client.post(
			'/api/presences/enregistrer',
			data=json.dumps({
				'classe_id': self.classe.id,
				'date': '2026-10-02',
				'periode': 'matin',
				'lignes': [{'eleve_id': self.eleve_autre_classe.id, 'statut': 'present'}],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(Presence.objects.count(), 0)


class PointageProfesseurTests(TestCase):
	def setUp(self):
		self.teacher_user = Utilisateur.objects.create(
			prenom='Mialy', nom='Prof', username='teacher-pointage',
			password='unused', role='professeur',
		)
		self.professeur = Professeur.objects.create(
			utilisateur=self.teacher_user, prenom='Mialy', nom='Prof',
		)
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Pointage', username='admin-pointage',
			password='unused', role='admin',
		)
		self.agent = Utilisateur.objects.create(
			prenom='Agent', nom='Test', username='agent-pointage',
			password='unused', role='agent',
		)

	def login_as(self, utilisateur):
		session = self.client.session
		session['user_id'] = utilisateur.id
		session.save()

	def test_monthly_sheet_groups_teacher_attendance_by_day(self):
		self.login_as(self.admin)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-01', statut='present',
			heure_entree=time(8, 0), heure_sortie=time(16, 0),
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-21', statut='retard',
			heure_entree=time(8, 30),
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-11-01', statut='absent',
		)

		response = self.client.get('/api/pointages/feuille', {'mois': '2026-10'})

		self.assertEqual(response.status_code, 200)
		result = response.json()
		self.assertEqual(result['mois'], '2026-10')
		self.assertEqual(len(result['jours']), 31)
		professeur = result['professeurs'][0]
		self.assertEqual(professeur['cases']['2026-10-01']['statut'], 'present')
		self.assertEqual(professeur['cases']['2026-10-21']['heure_entree'], '08:30')
		self.assertIsNone(professeur['cases']['2026-10-22'])
		self.assertEqual(professeur['nbPresent'], 1)
		self.assertEqual(professeur['nbRetard'], 1)
		self.assertEqual(professeur['nbAbsent'], 0)

	def test_monthly_sheet_rejects_invalid_month(self):
		self.login_as(self.admin)

		response = self.client.get('/api/pointages/feuille', {'mois': '2026-13'})

		self.assertEqual(response.status_code, 400)

	def test_agent_can_load_teacher_sheet_and_register_attendance(self):
		self.login_as(self.agent)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()
		feuille = self.client.get('/api/pointages/feuille', {'date': date})
		self.assertEqual(feuille.status_code, 200)
		self.assertEqual(feuille.json()['professeurs'][0]['professeur_id'], self.professeur.id)

		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({
				'date': date,
				'lignes': [{
					'professeur_id': self.professeur.id,
					'statut': 'retard',
					'heure_entree': '08:15',
					'heure_sortie': '16:30',
				}],
			}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		pointage = PointageProfesseur.objects.get(professeur=self.professeur)
		self.assertEqual(pointage.statut, 'retard')
		self.assertEqual(pointage.heure_entree, time(8, 15))
		self.assertEqual(pointage.heure_sortie, time(16, 30))
		self.assertEqual(PointageProfesseur.objects.count(), 1)

	def test_absence_clears_entry_and_exit_times(self):
		self.login_as(self.agent)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()
		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({
				'date': date,
				'lignes': [{
					'professeur_id': self.professeur.id,
					'statut': 'absent',
					'heure_entree': '08:15',
					'heure_sortie': '16:30',
				}],
			}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		pointage = PointageProfesseur.objects.get(professeur=self.professeur)
		self.assertEqual(pointage.statut, 'absent')
		self.assertIsNone(pointage.heure_entree)
		self.assertIsNone(pointage.heure_sortie)

	def test_entry_time_is_required_for_present_teacher(self):
		self.login_as(self.agent)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()
		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({
				'date': date,
				'lignes': [{'professeur_id': self.professeur.id, 'statut': 'present'}],
			}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(PointageProfesseur.objects.count(), 0)


	def test_exit_cannot_precede_entry(self):
		self.login_as(self.agent)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()
		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({
				'date': date,
				'lignes': [{
					'professeur_id': self.professeur.id,
					'statut': 'present',
					'heure_entree': '16:30',
					'heure_sortie': '08:15',
				}],
			}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(PointageProfesseur.objects.count(), 0)

	def test_agent_cannot_edit_past_date(self):
		self.login_as(self.agent)
		date = (timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')) - timedelta(days=1)).isoformat()
		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({'date': date, 'lignes': []}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 403)

	def test_admin_cannot_register_pointage(self):
		self.login_as(self.admin)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()
		feuille_jour = self.client.get('/api/pointages/feuille', {'date': date})
		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({
				'date': date,
				'lignes': [],
			}),
			content_type='application/json',
		)
		self.assertEqual(feuille_jour.status_code, 403)
		self.assertEqual(response.status_code, 403)
		self.assertEqual(PointageProfesseur.objects.count(), 0)

	def test_teacher_account_cannot_manage_the_sheet(self):
		self.login_as(self.teacher_user)
		response = self.client.get('/api/pointages/feuille')
		self.assertEqual(response.status_code, 403)


class AnneesScolairesTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Années', username='admin-annees', password='unused', role='admin',
		)
		self.annee = AnneeScolaire.objects.create(libelle='2025-2026', courante=True)
		self.classe = Classe.objects.create(nom='CM2', niveau='Primaire')
		self.matiere = Matiere.objects.create(nom='Français', coefficient_defaut=2)
		self.professeur = Professeur.objects.create(prenom='Mialy', nom='Rabe')
		Enseignement.objects.create(
			classe=self.classe,
			matiere=self.matiere,
			professeur=self.professeur,
			annee=self.annee,
		)
		session = self.client.session
		session['user_id'] = self.admin.id
		session.save()

	def test_new_school_year_copies_editable_subject_and_teacher_assignments(self):
		response = self.client.post(
			'/api/admin/annees/add',
			data=json.dumps({'libelle': '2026-2027'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		nouvelle_annee = AnneeScolaire.objects.get(libelle='2026-2027')
		nouvel_enseignement = Enseignement.objects.get(annee=nouvelle_annee)
		ancien_enseignement = Enseignement.objects.get(annee=self.annee)
		self.annee.refresh_from_db()
		self.assertFalse(self.annee.courante)
		self.assertTrue(nouvelle_annee.courante)
		self.assertEqual(nouvel_enseignement.professeur, self.professeur)
		self.assertEqual(nouvel_enseignement.get_coefficient(), 2)

		update_response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'enseignements',
				'matiere_id': self.matiere.id,
				'assignments': [{'classe_id': self.classe.id, 'coefficient': '4'}],
			}),
			content_type='application/json',
		)

		self.assertEqual(update_response.status_code, 200)
		nouvel_enseignement.refresh_from_db()
		ancien_enseignement.refresh_from_db()
		self.assertEqual(nouvel_enseignement.get_coefficient(), 4)
		self.assertEqual(ancien_enseignement.get_coefficient(), 2)
		self.assertEqual(nouvel_enseignement.professeur, self.professeur)


class InscriptionEleveTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Inscription', username='admin-inscription',
			password='unused', role='admin',
		)
		self.annee = AnneeScolaire.objects.create(libelle='2026-2027', courante=True)
		self.annee_precedente = AnneeScolaire.objects.create(libelle='2025-2026')
		self.classe = Classe.objects.create(
			nom='CP', niveau='Primaire', tarif_inscription=5000,
		)
		self.ancien_eleve = Eleve.objects.create(
			numero='2024-0007', prenom='Mialy', nom='Rabe', classe=self.classe,
			annee=self.annee_precedente,
		)
		self.numero_existant = Eleve.objects.create(
			numero='2026-0003', prenom='Andry', nom='Test', classe=self.classe,
			annee=self.annee,
		)
		self.login_as(self.admin)

	def login_as(self, utilisateur):
		session = self.client.session
		session['user_id'] = utilisateur.id
		session.save()

	def test_new_enrollment_generates_school_year_im_with_four_digit_sequence(self):
		Parametre.objects.update_or_create(
			cle='telephone_etablissement', defaults={'valeur': '+261 20 00 000 00'},
		)
		response = self.client.post(
			'/api/entree/apercu/inscription',
			data=json.dumps({
				'classe_id': self.classe.id,
				'type': 'inscription',
				'nom': 'Solo',
				'prenom': 'Tiana',
				'date_inscription': '2026-10-22',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		preview = self.client.get('/api/entree?preview=1').json()['preview']
		self.assertEqual(preview['saveData']['numero'], '2026-0004')
		self.assertTrue(preview['facture']['numero'].startswith('FAC-2026-'))
		self.assertNotEqual(preview['facture']['numero'], '2026-0004')
		self.assertEqual(preview['facture']['telephone'], '+261 20 00 000 00')
		saved = self.client.post('/api/entree/valider')
		self.assertEqual(saved.status_code, 200)
		self.assertTrue(Eleve.objects.filter(numero='2026-0004', annee=self.annee).exists())
		facture = Facture.objects.get(entree__type='inscription')
		self.assertEqual(facture.numero, preview['facture']['numero'])
		self.assertEqual(facture.statut, 'emise')
		self.assertEqual(facture.telephone_etablissement, '+261 20 00 000 00')
		self.assertEqual(
			self.client.get('/api/entree').json()['entrees'][0]['numero_facture'],
			facture.numero,
		)

	def test_reenrollment_search_selects_existing_im_and_reuses_identity(self):
		search = self.client.get('/api/entree/reinscription/rechercher', {'im': '2024-00'})
		self.assertEqual(search.status_code, 200)
		self.assertEqual(search.json()['eleves'], [{
			'id': self.ancien_eleve.id,
			'numero': '2024-0007',
			'nom': 'Rabe',
			'prenom': 'Mialy',
			'classe': 'CP',
			'annee': '2025-2026',
		}])

		preview_response = self.client.post(
			'/api/entree/apercu/inscription',
			data=json.dumps({
				'classe_id': self.classe.id,
				'type': 'reinscription',
				'eleve_id': self.ancien_eleve.id,
				'date_inscription': '2026-10-22',
			}),
			content_type='application/json',
		)
		self.assertEqual(preview_response.status_code, 200)
		preview = self.client.get('/api/entree?preview=1').json()['preview']
		self.assertEqual(preview['saveData']['numero'], '2024-0007')
		self.assertEqual(preview['facture']['nom'], 'Rabe')
		self.assertEqual(preview['facture']['prenom'], 'Mialy')

		saved = self.client.post('/api/entree/valider')
		self.assertEqual(saved.status_code, 200)
		self.assertEqual(
			Eleve.objects.filter(numero='2024-0007', annee=self.annee).count(), 1,
		)

	def test_reenrollment_rejects_student_without_previous_year_im(self):
		response = self.client.post(
			'/api/entree/apercu/inscription',
			data=json.dumps({
				'classe_id': self.classe.id,
				'type': 'reinscription',
				'nom': 'Saisi manuellement',
				'prenom': 'Interdit',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)

	def test_search_includes_students_already_in_current_school_year(self):
		response = self.client.get(
			'/api/entree/reinscription/rechercher',
			{'im': self.numero_existant.numero},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			[row['id'] for row in response.json()['eleves']],
			[self.numero_existant.id],
		)

	def test_current_year_reenrollment_updates_existing_record_without_duplicate(self):
		response = self.client.post(
			'/api/entree/apercu/inscription',
			data=json.dumps({
				'classe_id': self.classe.id,
				'type': 'reinscription',
				'eleve_id': self.numero_existant.id,
				'date_inscription': '2026-10-22',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		saved = self.client.post('/api/entree/valider')
		self.assertEqual(saved.status_code, 200)
		self.assertEqual(
			Eleve.objects.filter(numero=self.numero_existant.numero, annee=self.annee).count(),
			1,
		)
		self.assertTrue(Entree.objects.filter(
			eleve=self.numero_existant, type='reinscription',
		).exists())


class SalairesProfesseursTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Paie', username='admin-salaires',
			password='unused', role='admin',
		)
		self.agent = Utilisateur.objects.create(
			prenom='Agent', nom='Paie', username='agent-salaires',
			password='unused', role='agent',
		)
		self.professeur = Professeur.objects.create(
			prenom='Mialy', nom='Prof', taux_horaire=1000,
		)
		self.login_as(self.admin)

	def login_as(self, utilisateur):
		session = self.client.session
		session['user_id'] = utilisateur.id
		session.save()

	def test_monthly_salary_uses_completed_present_and_late_pointages(self):
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-01', statut='present',
			heure_entree=time(8, 0), heure_sortie=time(10, 15),
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-02', statut='retard',
			heure_entree=time(9, 0), heure_sortie=time(13, 0),
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-03', statut='absent',
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-04', statut='present',
			heure_entree=time(8, 0),
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-11-01', statut='present',
			heure_entree=time(8, 0), heure_sortie=time(12, 0),
		)

		response = self.client.get('/api/admin/salaires-professeurs', {'mois': '2026-10'})

		self.assertEqual(response.status_code, 200)
		salaire = response.json()['professeurs'][0]
		self.assertEqual(salaire['total_minutes'], 375)
		self.assertEqual(salaire['total_heures'], '6.250000')
		self.assertEqual(salaire['montant_total'], '6250.00')
		self.assertFalse(salaire['est_paye'])

	def test_payment_creates_receipt_and_keeps_paid_amount_unchanged(self):
		Parametre.objects.update_or_create(
			cle='telephone_etablissement', defaults={'valeur': '+261 34 00 000 00'},
		)
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-01', statut='present',
			heure_entree=time(8, 0), heure_sortie=time(10, 0),
		)
		response = self.client.post(
			f'/api/admin/salaires-professeurs/{self.professeur.id}/payer',
			data=json.dumps({'mois': '2026-10'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		facture = response.json()['facture']
		facture_enregistree = Facture.objects.get(fiche_paie__professeur=self.professeur)
		self.assertEqual(facture['numero'], facture_enregistree.numero)
		self.assertTrue(facture['numero'].startswith('FAC-2026-'))
		self.assertEqual(facture['telephone'], '+261 34 00 000 00')
		self.assertEqual(facture_enregistree.statut, 'emise')
		self.assertEqual(facture['professeur'], 'Mialy Prof')
		self.assertEqual(facture['total_heures'], '2.000000')
		self.assertEqual(facture['taux_horaire'], '1000.00')
		self.assertEqual(facture['montant_total'], '2000.00')
		self.assertTrue(FichePaieProf.objects.get(professeur=self.professeur).est_paye)

		self.professeur.taux_horaire = 2000
		self.professeur.save(update_fields=['taux_horaire'])
		salaires = self.client.get('/api/admin/salaires-professeurs', {'mois': '2026-10'})
		salaire = salaires.json()['professeurs'][0]
		self.assertEqual(salaire['taux_horaire'], '1000.00')
		self.assertEqual(salaire['montant_total'], '2000.00')
		self.assertTrue(salaire['est_paye'])

	def test_one_worked_minute_is_prorated_without_hour_rounding_loss(self):
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-01', statut='present',
			heure_entree=time(8, 0), heure_sortie=time(8, 1),
		)

		response = self.client.get('/api/admin/salaires-professeurs', {'mois': '2026-10'})

		self.assertEqual(response.status_code, 200)
		salaire = response.json()['professeurs'][0]
		self.assertEqual(salaire['total_minutes'], 1)
		self.assertEqual(salaire['total_heures'], '0.016667')
		self.assertEqual(salaire['montant_total'], '16.67')

	def test_agent_can_view_salary_and_mark_it_paid_but_cannot_change_rate(self):
		PointageProfesseur.objects.create(
			professeur=self.professeur, date='2026-10-01', statut='present',
			heure_entree=time(8, 0), heure_sortie=time(10, 0),
		)
		self.login_as(self.agent)

		salaires = self.client.get('/api/admin/salaires-professeurs', {'mois': '2026-10'})
		modification_taux = self.client.post(
			f'/api/admin/salaires-professeurs/{self.professeur.id}/taux',
			data=json.dumps({'taux_horaire': '2000'}),
			content_type='application/json',
		)
		paiement = self.client.post(
			f'/api/admin/salaires-professeurs/{self.professeur.id}/payer',
			data=json.dumps({'mois': '2026-10'}),
			content_type='application/json',
		)

		self.assertEqual(salaires.status_code, 200)
		self.assertEqual(salaires.json()['professeurs'][0]['taux_horaire'], '1000.00')
		self.assertEqual(modification_taux.status_code, 403)
		self.assertEqual(paiement.status_code, 200)
		self.assertTrue(FichePaieProf.objects.get(professeur=self.professeur).est_paye)
		self.professeur.refresh_from_db()
		self.assertEqual(str(self.professeur.taux_horaire), '1000.00')


class FacturationTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Factures', username='admin-factures',
			password='unused', role='admin',
		)
		session = self.client.session
		session['user_id'] = self.admin.id
		session.save()

	def test_school_phone_can_be_configured_and_is_returned_in_settings(self):
		response = self.client.post(
			'/api/admin/parametres/telephone',
			data=json.dumps({'telephone_etablissement': '+261 20 00 000 00'}),
			content_type='application/json',
		)
		settings = self.client.get('/api/admin/parametres')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(settings.status_code, 200)
		self.assertEqual(settings.json()['telephone'], '+261 20 00 000 00')

	def test_school_phone_rejects_values_over_50_characters(self):
		response = self.client.post(
			'/api/admin/parametres/telephone',
			data=json.dumps({'telephone_etablissement': '1' * 51}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)
		self.assertFalse(Parametre.objects.filter(cle='telephone_etablissement').exists())

	def test_book_rental_invoice_number_is_persisted_and_returned_in_history(self):
		annee = AnneeScolaire.objects.create(libelle='2026-2027', courante=True)
		classe = Classe.objects.create(nom='CP', niveau='Primaire')
		eleve = Eleve.objects.create(
			numero='2026-0001', prenom='Mialy', nom='Rabe', classe=classe, annee=annee,
		)
		Parametre.objects.create(cle='telephone_etablissement', valeur='020 00 000 00')
		preview_response = self.client.post(
			'/api/location-livres/apercu',
			data=json.dumps({
				'eleve_id': eleve.id, 'classe_id': classe.id, 'quantite': 2,
				'montant_unitaire': 500,
			}),
			content_type='application/json',
		)
		preview = preview_response.json()['preview']
		saved = self.client.post('/api/location-livres/valider')
		location = LocationBook.objects.get(eleve=eleve)
		facture = Facture.objects.get(location_livre=location)
		history = self.client.get('/api/location-livres').json()

		self.assertEqual(preview['facture']['telephone'], '020 00 000 00')
		self.assertTrue(preview['facture']['numero'].startswith('FAC-2026-'))
		self.assertEqual(saved.status_code, 200)
		self.assertEqual(facture.numero, preview['facture']['numero'])
		self.assertEqual(facture.statut, 'emise')
		self.assertEqual(history['locations'][0]['numero_facture'], facture.numero)


class StudentPaymentInvoiceTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Reçus', username='admin-recus', password='unused', role='admin',
		)
		self.annee = AnneeScolaire.objects.create(libelle='2026-2027', courante=True)
		self.classe = Classe.objects.create(
			nom='CP', niveau='Primaire', tarif_ecolage=500, tarif_fascicule=250,
		)
		self.eleve = Eleve.objects.create(
			numero='2026-0001', prenom='Mialy', nom='Rabe',
			classe=self.classe, annee=self.annee,
		)
		session = self.client.session
		session['user_id'] = self.admin.id
		session.save()

	def test_tuition_receipt_is_stored_with_invoice_number(self):
		preview_response = self.client.post(
			'/api/entree/apercu/ecolage',
			data=json.dumps({
				'eleve_id': self.eleve.id, 'classe_id': self.classe.id, 'mois': [0],
			}),
			content_type='application/json',
		)
		preview = preview_response.json()['preview']
		saved = self.client.post('/api/entree/valider')
		entree = Entree.objects.get(type='ecolage')
		facture = Facture.objects.get(entree=entree)

		self.assertEqual(saved.status_code, 200)
		self.assertEqual(facture.numero, preview['facture']['numero'])
		self.assertEqual(facture.statut, 'emise')

	def test_annual_payment_receipt_is_stored_with_invoice_number(self):
		preview_response = self.client.post(
			'/api/entree/apercu/fascicule',
			data=json.dumps({
				'eleve_id': self.eleve.id, 'classe_id': self.classe.id, 'payment_type': 'fascicule',
			}),
			content_type='application/json',
		)
		preview = preview_response.json()['preview']
		saved = self.client.post('/api/entree/valider')
		entree = Entree.objects.get(type='fascicule')
		facture = Facture.objects.get(entree=entree)

		self.assertEqual(saved.status_code, 200)
		self.assertEqual(facture.numero, preview['facture']['numero'])
		self.assertEqual(facture.statut, 'emise')

	def test_other_payment_receipt_is_stored_with_invoice_number(self):
		type_paiement = TypePaiement.objects.create(nom='Cantine', categorie='autre', montant=300)
		preview_response = self.client.post(
			'/api/entree/apercu/type-paiement',
			data=json.dumps({
				'eleve_id': self.eleve.id, 'classe_id': self.classe.id,
				'type_paiement_id': type_paiement.id,
			}),
			content_type='application/json',
		)
		preview = preview_response.json()['preview']
		saved = self.client.post('/api/entree/valider')
		entree = Entree.objects.get(type='Cantine')
		facture = Facture.objects.get(entree=entree)

		self.assertEqual(saved.status_code, 200)
		self.assertEqual(facture.numero, preview['facture']['numero'])
		self.assertEqual(facture.statut, 'emise')


class JournalOperationTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Journal', username='journal-admin', password='unused', role='admin',
		)
		self.agent = Utilisateur.objects.create(
			prenom='Agent', nom='Journal', username='journal-agent', password='unused', role='agent',
		)
		self.professeur = Professeur.objects.create(prenom='Mialy', nom='Prof')

	def login_as(self, utilisateur):
		session = self.client.session
		session['user_id'] = utilisateur.id
		session.save()

	def test_successful_write_is_logged_with_user_and_action(self):
		self.login_as(self.agent)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()

		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({
				'date': date,
				'lignes': [{
					'professeur_id': self.professeur.id,
					'statut': 'present',
					'heure_entree': '08:00',
				}],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		log = JournalOperation.objects.get(utilisateur=self.agent)
		self.assertEqual(log.utilisateur, self.agent)
		self.assertEqual(log.nom_utilisateur, 'Agent Journal')
		self.assertEqual(log.action, 'creation')
		self.assertIn('Mialy Prof', log.objet)

	def test_failed_write_does_not_create_a_business_log(self):
		self.login_as(self.agent)
		response = self.client.post(
			'/api/pointages/enregistrer',
			data=json.dumps({'date': 'invalid', 'lignes': []}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(JournalOperation.objects.count(), 0)

	def test_reads_are_not_logged(self):
		self.login_as(self.agent)
		agent_response = self.client.get('/api/pointages/feuille')
		self.assertEqual(agent_response.status_code, 200)
		self.assertEqual(JournalOperation.objects.count(), 0)

	def test_update_and_delete_are_logged_against_the_affected_teacher(self):
		self.login_as(self.agent)
		date = timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')).isoformat()
		payload = {
			'date': date,
			'lignes': [{
				'professeur_id': self.professeur.id,
				'statut': 'present',
				'heure_entree': '08:00',
			}],
		}
		self.client.post('/api/pointages/enregistrer', data=json.dumps(payload), content_type='application/json')
		payload['lignes'][0]['heure_entree'] = '08:10'
		self.client.post('/api/pointages/enregistrer', data=json.dumps(payload), content_type='application/json')
		token = set_audit_actor(self.agent)
		try:
			self.professeur.pointages.first().delete()
		finally:
			reset_audit_actor(token)

		operations = list(JournalOperation.objects.order_by('id'))
		self.assertEqual(
			[operation.action for operation in operations],
			['creation', 'modification', 'suppression'],
		)
		self.assertTrue(all('Mialy Prof' in operation.objet for operation in operations))

	def test_only_admin_can_read_operation_journal(self):
		self.login_as(self.agent)
		forbidden = self.client.get('/api/admin/journal')
		self.assertEqual(forbidden.status_code, 403)

		self.login_as(self.admin)
		allowed = self.client.get('/api/admin/journal')
		self.assertEqual(allowed.status_code, 200)
		self.assertEqual(allowed.json()['total'], 0)

	def test_admin_journal_shows_actor_action_and_target_only(self):
		token = set_audit_actor(self.agent)
		try:
			PointageProfesseur.objects.create(
				professeur=self.professeur,
				date=timezone.localdate(timezone=ZoneInfo('Indian/Antananarivo')),
				statut='present',
				heure_entree=time(8, 0),
			)
		finally:
			reset_audit_actor(token)
		self.login_as(self.admin)

		response = self.client.get('/api/admin/journal')

		self.assertEqual(response.status_code, 200)
		entry = response.json()['operations'][0]
		self.assertEqual(entry['utilisateur'], 'Agent Journal')
		self.assertEqual(entry['action'], 'Création / enregistrement')
		self.assertIn('Mialy Prof', entry['objet'])
		self.assertEqual(set(entry), {'id', 'date', 'utilisateur', 'role', 'action', 'objet'})


class RetardPaymentLogicTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Test', username='retard-admin-test', password='unused', role='admin'
		)
		self.annee = AnneeScolaire.objects.create(
			libelle='2024-2025', debut='2026-09-01', courante=True
		)
		self.classe = Classe.objects.create(nom='CP', niveau='Primaire', tarif_ecolage=100)
		self.eleve = Eleve.objects.create(
			numero='CP-RETARD', prenom='Mialy', nom='Test', classe=self.classe,
			annee=self.annee, date_inscription='2026-08-15',
		)
		session = self.client.session
		session['user_id'] = self.admin.id
		session.save()

	def test_pre_enrollment_starts_at_first_school_month_and_stops_at_current_month(self):
		mois = get_mois_facturables(self.eleve, 9, 2026, datetime(2026, 10, 15))

		self.assertEqual(mois, [0, 1])

	def test_future_school_months_can_be_selected_for_advance_payment(self):
		self.eleve.date_inscription = '2026-10-02'
		self.eleve.save(update_fields=['date_inscription'])

		mois = get_mois_facturables(
			self.eleve, 9, 2026, datetime(2026, 10, 15), inclure_mois_futurs=True
		)

		self.assertEqual(mois, list(range(1, 10)))

	def test_other_monthly_payment_does_not_mark_tuition_as_paid(self):
		type_paiement = TypePaiement.objects.create(nom='Cantine', categorie='mensuel', montant=50)
		MoisEcolage.objects.create(
			eleve=self.eleve, annee=self.annee, mois_index=0, type_paiement_id=type_paiement.id
		)

		status = calculate_eleve_status(self.eleve, self.annee, datetime(2026, 10, 1))

		self.assertEqual(status['nbMoisImpayes'], 2)
		self.assertEqual(status['montantDu'], 200)

	def test_tuition_and_other_monthly_payment_keep_separate_month_records(self):
		type_paiement = TypePaiement.objects.create(nom='Cantine', categorie='mensuel', montant=50)
		MoisEcolage.objects.create(
			eleve=self.eleve, annee=self.annee, mois_index=0, type_paiement_id=type_paiement.id
		)
		MoisEcolage.objects.create(
			eleve=self.eleve, annee=self.annee, mois_index=0, type_paiement_id=0
		)

		tuition_months = self.client.get(
			f'/api/misc/mois-eleve/{self.eleve.id}', {'type_paiement_id': 0}
		)
		other_months = self.client.get(
			f'/api/misc/mois-eleve/{self.eleve.id}', {'type_paiement_id': type_paiement.id}
		)

		self.assertEqual(tuition_months.json(), [0])
		self.assertEqual(other_months.json(), [0])

	def test_months_endpoint_includes_future_months_for_advance_payment(self):
		self.eleve.date_inscription = '2026-09-01'
		self.eleve.save(update_fields=['date_inscription'])

		response = self.client.get(f'/api/misc/mois-facturables/{self.eleve.id}')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['moisFacturables'], list(range(10)))

	def test_new_enrollment_is_not_immediately_overdue_when_year_label_is_stale(self):
		self.eleve.date_inscription = '2026-10-02'
		self.eleve.save(update_fields=['date_inscription'])

		status = calculate_eleve_status(self.eleve, self.annee, datetime(2026, 10, 2))

		self.assertEqual(status['detailsMois'][0]['nom'], 'Octobre')
		self.assertEqual(status['nbMoisEnRetard'], 0)
		self.assertEqual(status['statutGlobal'], 'À jour')

	def test_current_month_is_not_late_before_its_end(self):
		status = calculate_eleve_status(self.eleve, self.annee, datetime(2026, 9, 30, 23, 59, 59))

		self.assertEqual(status['joursRetardGlobal'], 0)
		self.assertEqual(status['statutGlobal'], 'À jour')

	def test_month_becomes_late_the_day_after_its_end(self):
		status = calculate_eleve_status(self.eleve, self.annee, datetime(2026, 10, 1))

		self.assertEqual(status['joursRetardGlobal'], 1)
		self.assertEqual(status['statutGlobal'], 'Avertissement')
		self.assertEqual(status['nbMoisImpayes'], 2)
		self.assertEqual(status['nbMoisEnRetard'], 1)
		self.assertEqual(status['nbMoisImpayesNonEchus'], 1)
		self.assertEqual(status['moisEnRetardNoms'], ['Septembre'])
		self.assertEqual(status['moisImpayesNonEchusNoms'], ['Octobre'])

	def test_en_retard_endpoint_returns_success(self):
		response = self.client.get('/api/retards/en-retard')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['eleves'][0]['moisImpayésNoms'], 'Septembre')

	def test_mois_impayes_excludes_current_month_for_new_enrollment(self):
		self.eleve.date_inscription = datetime.now().date().isoformat()
		self.eleve.save(update_fields=['date_inscription'])

		response = self.client.get('/api/retards/mois-impayes')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['eleves'], [])


class BulletinNotesApiTests(TestCase):
	def setUp(self):
		self.admin = Utilisateur.objects.create(
			prenom='Admin', nom='Notes', username='notes-admin', password='unused', role='admin'
		)
		self.professor_user = Utilisateur.objects.create(
			prenom='Professeur', nom='Notes', username='notes-professor', password='unused', role='professeur'
		)
		self.professeur = Professeur.objects.create(
			utilisateur=self.professor_user, prenom='Professeur', nom='Notes',
		)
		self.annee = AnneeScolaire.objects.create(libelle='2026-2027', courante=True)
		self.classe = Classe.objects.create(nom='CM2', niveau='Primaire')
		self.autre_classe = Classe.objects.create(nom='CM1', niveau='Primaire')
		self.eleve = Eleve.objects.create(
			numero='CM2-001', prenom='Mialy', nom='Rabe', classe=self.classe, annee=self.annee
		)
		self.autre_eleve = Eleve.objects.create(
			numero='CM2-002', prenom='Tiana', nom='Andry', classe=self.classe, annee=self.annee
		)
		self.sans_note = Eleve.objects.create(
			numero='CM2-003', prenom='Fara', nom='Solo', classe=self.classe, annee=self.annee
		)
		self.hors_classe = Eleve.objects.create(
			numero='CM1-001', prenom='Lova', nom='Rabe', classe=self.autre_classe, annee=self.annee
		)
		self.francais = Matiere.objects.create(nom='Français', coefficient_defaut=2)
		self.maths = Matiere.objects.create(nom='Mathématiques', coefficient_defaut=1)
		self.francais_enseignement = Enseignement.objects.create(
			classe=self.classe, matiere=self.francais, annee=self.annee,
		)
		self.maths_enseignement = Enseignement.objects.create(
			classe=self.classe, matiere=self.maths, annee=self.annee
		)
		self.francais_eval = Evaluation.objects.create(
			enseignement=self.francais_enseignement, titre='Dictée', periode='trimestre_1', note_sur=10
		)
		self.maths_eval = Evaluation.objects.create(
			enseignement=self.maths_enseignement, titre='Calcul', periode='trimestre_1', note_sur=20
		)
		session = self.client.session
		session['user_id'] = self.admin.id
		session.save()

	def login_as_professeur(self):
		self.francais_enseignement.professeur = self.professeur
		self.francais_enseignement.save(update_fields=['professeur'])
		session = self.client.session
		session['user_id'] = self.professor_user.id
		session.save()

	def test_note_is_created_then_updated_without_duplicates(self):
		self.login_as_professeur()
		payload = {'eleve_id': self.eleve.id, 'evaluation_id': self.francais_eval.id, 'valeur': '8.5'}
		first = self.client.post('/api/academique/notes', data=json.dumps(payload), content_type='application/json')
		payload['valeur'] = '9'
		second = self.client.post('/api/academique/notes', data=json.dumps(payload), content_type='application/json')

		self.assertEqual(first.status_code, 200)
		self.assertTrue(first.json()['created'])
		self.assertEqual(second.status_code, 200)
		self.assertFalse(second.json()['created'])
		self.assertEqual(Note.objects.filter(eleve=self.eleve, evaluation=self.francais_eval).count(), 1)
		self.assertEqual(str(Note.objects.get(eleve=self.eleve, evaluation=self.francais_eval).valeur), '9.00')

	def test_note_rejects_value_above_max_and_student_from_another_class(self):
		self.login_as_professeur()
		too_high = self.client.post(
			'/api/academique/notes',
			data=json.dumps({'eleve_id': self.eleve.id, 'evaluation_id': self.francais_eval.id, 'valeur': 11}),
			content_type='application/json',
		)
		wrong_class = self.client.post(
			'/api/academique/notes',
			data=json.dumps({'eleve_id': self.hors_classe.id, 'evaluation_id': self.francais_eval.id, 'valeur': 8}),
			content_type='application/json',
		)

		self.assertEqual(too_high.status_code, 400)
		self.assertEqual(wrong_class.status_code, 404)
		self.assertEqual(Note.objects.count(), 0)

	def test_student_search_matches_name_and_number_within_selected_class(self):
		self.login_as_professeur()
		response = self.client.get('/api/academique/eleves', {
			'classe_id': self.classe.id, 'evaluation_id': self.francais_eval.id, 'q': 'CM2-001',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual([eleve['id'] for eleve in response.json()['eleves']], [self.eleve.id])

	def test_student_list_returns_full_class_roster_without_search(self):
		self.login_as_professeur()
		Note.objects.create(
			evaluation=self.francais_eval, eleve=self.eleve, valeur=8, appreciation='À revoir',
		)
		response = self.client.get('/api/academique/eleves', {
			'classe_id': self.classe.id, 'evaluation_id': self.francais_eval.id,
		})

		self.assertEqual(response.status_code, 200)
		eleves = response.json()['eleves']
		self.assertEqual({eleve['id'] for eleve in eleves}, {
			self.eleve.id, self.autre_eleve.id, self.sans_note.id,
		})
		eleve_avec_note = next(eleve for eleve in eleves if eleve['id'] == self.eleve.id)
		self.assertEqual(eleve_avec_note['note'], '8.00')
		self.assertEqual(eleve_avec_note['appreciation'], 'À revoir')
		self.assertIsNone(next(eleve for eleve in eleves if eleve['id'] == self.sans_note.id)['note'])

	def test_admin_and_agent_cannot_search_or_enter_grades(self):
		agent = Utilisateur.objects.create(
			prenom='Agent', nom='Notes', username='notes-agent', password='unused', role='agent',
		)
		payload = {
			'eleve_id': self.eleve.id,
			'evaluation_id': self.francais_eval.id,
			'valeur': '9',
		}

		for utilisateur in (self.admin, agent):
			session = self.client.session
			session['user_id'] = utilisateur.id
			session.save()
			search = self.client.get('/api/academique/eleves', {
				'classe_id': self.classe.id, 'evaluation_id': self.francais_eval.id,
			})
			save = self.client.post(
				'/api/academique/notes', data=json.dumps(payload), content_type='application/json',
			)

			self.assertEqual(search.status_code, 403)
			self.assertEqual(save.status_code, 403)

		self.assertEqual(Note.objects.count(), 0)

	def test_bulletin_normalizes_notes_weights_subjects_and_ranks_students(self):
		Note.objects.create(
			evaluation=self.francais_eval, eleve=self.eleve, valeur=8, appreciation='Très bien'
		)
		Note.objects.create(evaluation=self.maths_eval, eleve=self.eleve, valeur=10)
		Note.objects.create(evaluation=self.francais_eval, eleve=self.autre_eleve, valeur=6)
		Note.objects.create(evaluation=self.maths_eval, eleve=self.autre_eleve, valeur=20)

		response = self.client.get('/api/academique/bulletin', {
			'eleve_id': self.eleve.id, 'periode': 'trimestre_1',
		})
		bulletin = response.json()

		self.assertEqual(response.status_code, 200)
		self.assertEqual(bulletin['moyenne_generale'], 14)
		self.assertEqual(bulletin['rang'], 2)
		self.assertEqual(bulletin['effectif_classe'], 2)
		self.assertEqual(bulletin['matieres'][0]['moyenne'], 16)
		self.assertEqual(bulletin['matieres'][0]['coefficient'], 2)
		self.assertEqual(bulletin['matieres'][0]['total_pondere'], 32)
		self.assertEqual(bulletin['matieres'][0]['appreciation'], 'Très bien')

	def test_bulletin_only_includes_notes_from_selected_period(self):
		second_period_evaluation = Evaluation.objects.create(
			enseignement=self.francais_enseignement, titre='Rédaction',
			periode='trimestre_2', note_sur=20,
		)
		Note.objects.create(evaluation=self.francais_eval, eleve=self.eleve, valeur=8)
		Note.objects.create(evaluation=second_period_evaluation, eleve=self.eleve, valeur=18)

		first_period_response = self.client.get('/api/academique/bulletin', {
			'eleve_id': self.eleve.id, 'periode': 'trimestre_1',
		})
		second_period_response = self.client.get('/api/academique/bulletin', {
			'eleve_id': self.eleve.id, 'periode': 'trimestre_2',
		})

		self.assertEqual(first_period_response.status_code, 200)
		self.assertEqual(second_period_response.status_code, 200)
		first_period_bulletin = first_period_response.json()
		second_period_bulletin = second_period_response.json()
		french_first_period = next(
			matiere for matiere in first_period_bulletin['matieres']
			if matiere['matiere'] == self.francais.nom
		)
		french_second_period = next(
			matiere for matiere in second_period_bulletin['matieres']
			if matiere['matiere'] == self.francais.nom
		)
		self.assertEqual([note['evaluation'] for note in french_first_period['notes']], ['Dictée'])
		self.assertEqual(french_first_period['moyenne'], 16)
		self.assertEqual([note['evaluation'] for note in french_second_period['notes']], ['Rédaction'])
		self.assertEqual(french_second_period['moyenne'], 18)
		self.assertEqual(first_period_bulletin['periode'], 'trimestre_1')
		self.assertEqual(second_period_bulletin['periode'], 'trimestre_2')

	def test_only_admin_can_configure_curriculum(self):
		agent = Utilisateur.objects.create(
			prenom='Agent', nom='Notes', username='notes-agent', password='unused', role='agent'
		)
		session = self.client.session
		session['user_id'] = agent.id
		session.save()

		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({'action': 'matiere', 'nom': 'Sciences'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 403)

	def test_admin_can_create_subject_assignment_and_evaluation(self):
		matiere_response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({'action': 'matiere', 'nom': 'Sciences', 'coefficient_defaut': 2}),
			content_type='application/json',
		)
		matiere_id = matiere_response.json()['matiere_id']
		enseignement_response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'enseignement', 'classe_id': self.classe.id, 'matiere_id': matiere_id,
			}),
			content_type='application/json',
		)
		evaluation_response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'evaluation', 'enseignement_id': enseignement_response.json()['enseignement_id'],
				'titre': 'Contrôle', 'periode': 'trimestre_1', 'note_sur': '20',
			}),
			content_type='application/json',
		)

		self.assertEqual(matiere_response.status_code, 200)
		self.assertEqual(enseignement_response.status_code, 200)
		self.assertEqual(evaluation_response.status_code, 201)
		self.assertEqual(Evaluation.objects.get(id=evaluation_response.json()['evaluation_id']).titre, 'Contrôle')

	def test_admin_can_create_evaluations_for_multiple_classes(self):
		autre_enseignement = Enseignement.objects.create(
			classe=self.autre_classe, matiere=self.francais, annee=self.annee,
		)
		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'evaluation',
				'matiere_id': self.francais.id,
				'enseignement_ids': [self.francais_enseignement.id, autre_enseignement.id],
				'titre': 'Contrôle commun',
				'periode': 'trimestre_1',
				'note_sur': '20',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()['count'], 2)
		evaluations = Evaluation.objects.filter(id__in=response.json()['evaluation_ids'])
		self.assertEqual(evaluations.count(), 2)
		self.assertEqual(set(evaluations.values_list('enseignement_id', flat=True)), {
			self.francais_enseignement.id, autre_enseignement.id,
		})
		self.assertEqual(set(evaluations.values_list('titre', flat=True)), {'Contrôle commun'})

	def test_admin_can_create_professor_account_with_course_assignments(self):
		response = self.client.post(
			'/api/admin/professeurs/add',
			data=json.dumps({
				'prenom': 'Lina',
				'nom': 'Rabe',
				'username': 'prof-lina',
				'password': 'secret123',
				'enseignement_ids': [self.francais_enseignement.id],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 201)
		professeur = Utilisateur.objects.get(username='prof-lina')
		self.assertEqual(professeur.role, 'professeur')
		self.assertEqual(professeur.profil_professeur.prenom, 'Lina')
		self.francais_enseignement.refresh_from_db()
		self.assertEqual(self.francais_enseignement.professeur, professeur.profil_professeur)
		login = self.client.post(
			'/api/auth/login',
			data=json.dumps({'username': 'prof-lina', 'password': 'secret123'}),
			content_type='application/json',
		)
		self.assertEqual(login.status_code, 200)
		self.assertEqual(login.json()['user']['role'], 'professeur')
		self.assertEqual(login.json()['redirect'], '/evaluations')

	def test_admin_can_enable_login_for_existing_professor_record(self):
		profil = Professeur.objects.create(prenom='Lina', nom='Rabe')
		self.francais_enseignement.professeur = profil
		self.francais_enseignement.save(update_fields=['professeur'])

		response = self.client.post(
			f'/api/admin/professeurs/{profil.id}/edit',
			data=json.dumps({
				'prenom': 'Lina',
				'nom': 'Rabe',
				'username': 'prof-lina',
				'password': 'secret123',
				'enseignement_ids': [self.francais_enseignement.id],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		profil.refresh_from_db()
		self.assertEqual(profil.utilisateur.role, 'professeur')
		self.assertEqual(profil.utilisateur.username, 'prof-lina')

	def test_professor_can_create_evaluations_only_for_assigned_courses(self):
		professeur_user = Utilisateur.objects.create(
			prenom='Lina', nom='Rabe', username='prof-lina', password='unused', role='professeur'
		)
		profil = Professeur.objects.create(utilisateur=professeur_user, prenom='Lina', nom='Rabe')
		self.francais_enseignement.professeur = profil
		self.francais_enseignement.save(update_fields=['professeur'])
		session = self.client.session
		session['user_id'] = professeur_user.id
		session.save()

		context = self.client.get('/api/academique/contexte')
		evaluation_count = Evaluation.objects.count()
		student_list = self.client.get('/api/academique/eleves', {
			'classe_id': self.classe.id,
			'evaluation_id': self.francais_eval.id,
		})
		own_note = self.client.post(
			'/api/academique/notes',
			data=json.dumps({
				'eleve_id': self.eleve.id,
				'evaluation_id': self.francais_eval.id,
				'valeur': '9',
			}),
			content_type='application/json',
		)
		unassigned_student_list = self.client.get('/api/academique/eleves', {
			'classe_id': self.classe.id,
			'evaluation_id': self.maths_eval.id,
		})
		unassigned_note = self.client.post(
			'/api/academique/notes',
			data=json.dumps({
				'eleve_id': self.eleve.id,
				'evaluation_id': self.maths_eval.id,
				'valeur': '17',
			}),
			content_type='application/json',
		)
		created = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'evaluation',
				'enseignement_id': self.francais_enseignement.id,
				'titre': 'Rédaction',
				'periode': 'trimestre_2',
				'note_sur': '20',
			}),
			content_type='application/json',
		)
		unassigned = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'evaluation',
				'enseignement_id': self.maths_enseignement.id,
				'titre': 'Calcul',
				'periode': 'trimestre_2',
				'note_sur': '20',
			}),
			content_type='application/json',
		)
		agent_api = self.client.get('/api/entree')

		self.assertEqual(context.status_code, 200)
		self.assertEqual([item['id'] for item in context.json()['enseignements']], [self.francais_enseignement.id])
		self.assertEqual(student_list.status_code, 200)
		self.assertEqual({row['id'] for row in student_list.json()['eleves']}, {
			self.eleve.id, self.autre_eleve.id, self.sans_note.id,
		})
		self.assertEqual(own_note.status_code, 200)
		self.assertEqual(unassigned_student_list.status_code, 404)
		self.assertEqual(unassigned_note.status_code, 404)
		self.assertEqual(created.status_code, 201)
		self.assertEqual(unassigned.status_code, 404)
		self.assertEqual(agent_api.status_code, 403)
		self.assertEqual(Evaluation.objects.count(), evaluation_count + 1)
		self.assertTrue(Evaluation.objects.filter(
			enseignement=self.francais_enseignement, titre='Rédaction',
		).exists())

	def test_bulk_evaluation_rejects_assignments_from_another_subject(self):
		count_before = Evaluation.objects.count()
		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'evaluation',
				'matiere_id': self.francais.id,
				'enseignement_ids': [self.francais_enseignement.id, self.maths_enseignement.id],
				'titre': 'Contrôle commun',
				'periode': 'trimestre_1',
				'note_sur': '20',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(Evaluation.objects.count(), count_before)

	def test_admin_can_associate_subject_with_multiple_classes(self):
		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'enseignements',
				'matiere_id': self.francais.id,
				'assignments': [
					{'classe_id': self.classe.id, 'coefficient': '3'},
					{'classe_id': self.autre_classe.id, 'coefficient': ''},
				],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['count'], 2)
		self.francais_enseignement.refresh_from_db()
		self.assertEqual(self.francais_enseignement.coefficient, 3)
		self.assertTrue(Enseignement.objects.filter(
			classe=self.autre_classe, matiere=self.francais, annee=self.annee, coefficient__isnull=True
		).exists())

	def test_bulk_subject_association_rolls_back_if_a_class_is_missing(self):
		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'enseignements',
				'matiere_id': self.francais.id,
				'assignments': [
					{'classe_id': self.classe.id, 'coefficient': '3'},
					{'classe_id': 999999, 'coefficient': '2'},
				],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 404)
		self.francais_enseignement.refresh_from_db()
		self.assertIsNone(self.francais_enseignement.coefficient)

	def test_bulk_subject_association_validates_all_coefficients_before_saving(self):
		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'enseignements',
				'matiere_id': self.francais.id,
				'assignments': [
					{'classe_id': self.classe.id, 'coefficient': '3'},
					{'classe_id': self.autre_classe.id, 'coefficient': '0'},
				],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)
		self.francais_enseignement.refresh_from_db()
		self.assertIsNone(self.francais_enseignement.coefficient)
		self.assertFalse(Enseignement.objects.filter(
			classe=self.autre_classe, matiere=self.francais, annee=self.annee
		).exists())

	def test_admin_can_update_subject_coefficient(self):
		response = self.client.post(
			'/api/academique/configuration',
			data=json.dumps({
				'action': 'matiere', 'matiere_id': self.francais.id,
				'nom': self.francais.nom, 'code': '', 'coefficient_defaut': 4,
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		self.francais.refresh_from_db()
		self.assertEqual(self.francais.coefficient_defaut, 4)

	def test_academic_context_lists_classes_without_students(self):
		Classe.objects.create(nom='CP', niveau='Primaire')

		response = self.client.get('/api/academique/contexte')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			{classe['nom'] for classe in response.json()['classes']},
			{'CM1', 'CM2', 'CP'},
		)
