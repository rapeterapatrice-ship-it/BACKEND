from django.utils.deprecation import MiddlewareMixin

from .audit import reset_audit_actor, set_audit_actor


class AuditLogMiddleware(MiddlewareMixin):
    """Makes the current application user available to model audit signals."""

    def process_request(self, request):
        from .auth import get_current_user

        request._audit_actor_token = set_audit_actor(get_current_user(request))

    def process_response(self, request, response):
        token = getattr(request, '_audit_actor_token', None)
        if token is not None:
            reset_audit_actor(token)
        return response
