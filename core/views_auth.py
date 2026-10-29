from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Utilisateur
from .serializers import LoginSerializer, ChangePasswordSerializer, SessionUserSerializer
from .auth import check_password, hash_password, get_current_user, require_academic_auth
from .helpers import get_param


@api_view(['POST'])
def login_view(request):
    payload = LoginSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    username = payload.validated_data['username']
    password = payload.validated_data['password']

    try:
        user = Utilisateur.objects.get(username=username)
    except Utilisateur.DoesNotExist:
        return Response({'error': 'Identifiants incorrects'}, status=400)

    if not user.actif:
        return Response({'error': 'Compte suspendu'}, status=400)

    if not check_password(password, user.password):
        return Response({'error': 'Identifiants incorrects'}, status=400)

    request.session['user_id'] = user.id
    request.session.save()

    redirect_to = '/' if user.role == 'admin' else (
        '/evaluations' if user.role == 'professeur' else '/entree'
    )
    return Response({'user': SessionUserSerializer(user).data, 'redirect': redirect_to})


@api_view(['POST'])
def logout_view(request):
    request.session.flush()
    return Response({'ok': True})


@api_view(['GET'])
def me_view(request):
    user = get_current_user(request)
    if not user:
        return Response({'user': None})
    return Response({
        'user': SessionUserSerializer(user).data,
        'nomEtablissement': get_param('nom_etablissement', 'EduFinance'),
        'themeCouleur': get_param('theme_couleur', 'green'),
        'logoUrl': get_param('logo_url', ''),
    })


@api_view(['POST'])
@require_academic_auth
def change_password_view(request):
    payload = ChangePasswordSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    current = payload.validated_data['current']
    newpwd = payload.validated_data['newpwd']
    confirm = payload.validated_data['confirm']

    user = request.current_user
    if not check_password(current, user.password):
        return Response({'error': 'Mot de passe actuel incorrect'}, status=400)
    if newpwd != confirm:
        return Response({'error': 'Les mots de passe ne correspondent pas'}, status=400)

    user.password = hash_password(newpwd)
    user.save()
    return Response({'ok': True})
