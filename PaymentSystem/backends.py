from django.contrib.auth.backends import BaseBackend
from .models import CustomUser


class PhoneNumberPincodeBackend(BaseBackend):
    def authenticate(self, request, phone_number=None, pincode=None, **kwargs):
        try:
            user = CustomUser.objects.get(phone_number=phone_number)
            if user.check_password(pincode):  # Check if the pincode matches the hashed password
                return user
        except CustomUser.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return None
