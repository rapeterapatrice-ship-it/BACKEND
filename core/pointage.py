from datetime import datetime, time

from .helpers import get_param


def pause_recreation():
    debut = get_param('pause_recreation_debut', '')
    fin = get_param('pause_recreation_fin', '')
    if not debut and not fin:
        return None
    return {'debut': debut, 'fin': fin}


def duree_travail_minutes(date, heure_entree, heure_sortie, pause=None):
    if not heure_entree or not heure_sortie:
        return None

    entree = datetime.combine(date, heure_entree)
    sortie = datetime.combine(date, heure_sortie)
    minutes = int((sortie - entree).total_seconds() // 60)
    if pause and pause['debut'] and pause['fin']:
        debut_pause = datetime.combine(date, time.fromisoformat(pause['debut']))
        fin_pause = datetime.combine(date, time.fromisoformat(pause['fin']))
        chevauchement = max(
            0,
            int((min(sortie, fin_pause) - max(entree, debut_pause)).total_seconds() // 60),
        )
        minutes -= chevauchement
    return max(0, minutes)
