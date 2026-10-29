from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model
from django.db.models.signals import pre_delete, post_save
from django.dispatch import receiver

from .audit import get_audit_actor
from .models import JournalOperation


def _record_operation(instance, action):
    if instance._meta.app_label != 'core' or isinstance(instance, JournalOperation):
        return

    utilisateur = get_audit_actor()
    if not utilisateur:
        return

    model_name = instance._meta.verbose_name
    try:
        objet = str(instance)
    except (AttributeError, ObjectDoesNotExist, TypeError, ValueError):
        objet = f'{model_name} #{instance.pk}'
    if type(instance).__str__ is Model.__str__:
        details = []
        for field_name in (
            'prenom', 'nom', 'numero', 'num_location', 'libelle', 'titre',
            'type', 'motif', 'eleve_nom', 'classe_nom', 'mois_index',
            'date', 'date_location', 'statut', 'cle',
        ):
            value = getattr(instance, field_name, None)
            if value not in (None, ''):
                details.append(str(value))
        for relation_name in ('eleve', 'classe', 'professeur', 'enseignement', 'evaluation'):
            try:
                related = getattr(instance, relation_name, None)
                related_label = str(related) if related is not None else None
            except ObjectDoesNotExist:
                related_label = None
            if related_label:
                details.append(related_label)
        objet = ' — '.join(details) if details else f'{model_name} #{instance.pk}'
    objet = f'{model_name.capitalize()} : {objet}'[:500]

    JournalOperation.objects.create(
        utilisateur=utilisateur,
        nom_utilisateur=f'{utilisateur.prenom} {utilisateur.nom}'.strip(),
        role_utilisateur=utilisateur.role,
        action=action,
        objet=objet,
    )


@receiver(post_save)
def journaliser_enregistrement(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    _record_operation(instance, 'creation' if created else 'modification')


@receiver(pre_delete)
def journaliser_suppression(sender, instance, **kwargs):
    _record_operation(instance, 'suppression')
