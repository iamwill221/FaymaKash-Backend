from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

class FourDigitPasswordValidator:
    def validate(self, password, user=None):
        if len(password) != 4 or not password.isdigit():
            raise ValidationError(
                _("Password must be exactly 4 digits."),
                code="password_not_four_digits",
            )

    def get_help_text(self):
        return _("Your password must be exactly 4 digits.")