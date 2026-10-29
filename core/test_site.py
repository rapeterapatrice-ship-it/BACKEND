import json

from django.test import TestCase

from .models import Classe, Parametre, Utilisateur


class PublicSiteTests(TestCase):
    def test_public_site_shows_public_content_and_class_fees(self):
        Parametre.objects.create(cle='nom_etablissement', valeur='École Horizon')
        Classe.objects.create(
            nom='CP1', niveau='Primaire', tarif_inscription=12000,
            tarif_ecolage=25000, tarif_fascicule=5000, tarif_location=3000,
        )

        response = self.client.get('/api/site-web')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['nom'], 'École Horizon')
        self.assertEqual(payload['config']['accueilTitre'], 'L’avenir commence ici.')
        self.assertEqual(payload['tarifs'][0]['nom'], 'CP1')
        self.assertEqual(payload['tarifs'][0]['tarif_ecolage'], 25000)


class AdminSiteConfigTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(
            prenom='Admin', nom='Site', username='admin-site', password='unused', role='admin',
        )

    def login_as_admin(self):
        session = self.client.session
        session['user_id'] = self.admin.id
        session.save()

    def test_site_config_is_restricted_to_admins(self):
        self.assertEqual(self.client.get('/api/admin/site-web').status_code, 403)
        self.assertEqual(self.client.post('/api/admin/site-web', data='{}', content_type='application/json').status_code, 403)

    def test_admin_can_publish_site_content(self):
        self.login_as_admin()
        config = {
            'accueilTitre': 'Bienvenue à Horizon',
            'accueilSousTitre': 'Une école ouverte à tous',
            'accueilDescription': 'Apprendre ensemble.',
            'actualites': [{
                'titre': 'Rentrée scolaire',
                'date': '1er septembre',
                'categorie': 'Vie scolaire',
                'description': 'La rentrée approche.',
            }],
            'resultatsTitre': 'Nos réussites',
            'resultatsDescription': 'Une année de progrès.',
            'fraisDescription': 'Les tarifs de l’année.',
            'contactAdresse': 'Antananarivo',
            'contactEmail': 'contact@example.org',
            'contactTelephone': '+261 20 00 000 00',
        }

        response = self.client.post(
            '/api/admin/site-web',
            data=json.dumps(config),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(Parametre.objects.get(cle='site_web_config').valeur), config)
        published = self.client.get('/api/site-web').json()
        self.assertEqual(published['config']['actualites'][0]['titre'], 'Rentrée scolaire')

    def test_admin_cannot_publish_invalid_email(self):
        self.login_as_admin()
        response = self.client.post(
            '/api/admin/site-web',
            data=json.dumps({'contactEmail': 'not-an-email'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Parametre.objects.filter(cle='site_web_config').exists())
