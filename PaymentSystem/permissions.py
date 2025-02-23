from rest_framework.permissions import BasePermission

class IsClient(BasePermission):
    def has_permission(self, request, view):
        return request.user.user_type == 'client'

class IsManager(BasePermission):
    def has_permission(self, request, view):
        return request.user.user_type == 'manager'

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.user_type == 'admin'