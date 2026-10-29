import functools
import bcrypt
from rest_framework.response import Response

from .models import Utilisateur


def hash_password(plain):
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt(10)).decode('utf-8')


def check_password(plain, hashed):
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def get_current_user(request):
    """Retourne l'utilisateur de la session courante (équivalent req.session.user)."""
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    try:
        return Utilisateur.objects.get(id=user_id, actif=True)
    except Utilisateur.DoesNotExist:
        return None


def require_auth(view_func):
    """Authentifie les administrateurs et agents des fonctions opérationnelles."""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return Response({'error': 'Non authentifié'}, status=401)
        if user.role not in ('admin', 'agent'):
            return Response({'error': 'Accès réservé aux agents et administrateurs'}, status=403)
        request.current_user = user
        return view_func(request, *args, **kwargs)
    return wrapper


def require_academic_auth(view_func):
    """Authentifie tout utilisateur pour les fonctions académiques autorisées par rôle."""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return Response({'error': 'Non authentifié'}, status=401)
        request.current_user = user
        return view_func(request, *args, **kwargs)
    return wrapper


def require_admin(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user or user.role != 'admin':
            return Response({'error': 'Accès refusé'}, status=403)
        request.current_user = user
        return view_func(request, *args, **kwargs)
    return wrapper
