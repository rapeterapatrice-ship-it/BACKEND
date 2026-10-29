from django.core.paginator import Paginator
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth import require_admin
from .models import JournalOperation


@api_view(['GET'])
@require_admin
def journal_operations_view(request):
    try:
        page_number = max(int(request.query_params.get('page', 1)), 1)
    except (TypeError, ValueError):
        return Response({'error': 'Numéro de page invalide'}, status=400)

    paginator = Paginator(
        JournalOperation.objects.select_related('utilisateur').all(),
        50,
    )
    page = paginator.get_page(page_number)
    operations = [{
        'id': operation.id,
        'date': operation.date_operation.isoformat(),
        'utilisateur': operation.nom_utilisateur,
        'role': operation.role_utilisateur,
        'action': operation.get_action_display(),
        'objet': operation.objet,
    } for operation in page.object_list]

    return Response({
        'operations': operations,
        'page': page.number,
        'pages': paginator.num_pages,
        'total': paginator.count,
    })
