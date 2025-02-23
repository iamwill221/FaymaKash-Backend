from django.db.models import Q
from django.utils import timezone
from djoser.serializers import UserCreateSerializer, UserSerializer
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from typing import Dict, Any, Optional
from .models import (
    CustomUser, InternalTransaction, ExternalDepositTransaction,
    ExternalWithdrawalTransaction, TransactionType, UserType,
    TransactionStatus, MOMO_SERVICES, NFCCard
)
from .transactions_momo import TransactionError, ServiceType


class OtpRequestSerializer(serializers.Serializer):
    phone_number = PhoneNumberField(required=True)


class OtpVerifySerializer(serializers.Serializer):
    phone_number = PhoneNumberField(required=True)
    otp = serializers.CharField(required=True, min_length=6, max_length=6)


class CustomUserCreateSerializer(UserCreateSerializer):
    pincode = serializers.CharField(write_only=True)

    class Meta(UserCreateSerializer.Meta):
        model = CustomUser
        fields = ('phone_number', 'pincode', 'firstname', 'lastname', 'cash', 'user_type')

    def validate_pincode(self, value: str) -> str:
        """Validate that pincode is a 4-digit number."""
        if not (len(value) == 4 and value.isdigit()):
            raise serializers.ValidationError("Le code PIN doit être composé de 4 chiffres.")
        return value

    def validate_user_type(self, value: str) -> str:
        """Additional validation for user type."""
        if value not in UserType.values:
            raise serializers.ValidationError("Type d'utilisateur invalide.")
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        attrs['password'] = attrs.pop('pincode')
        return super().validate(attrs)


class CustomUserSerializer(UserSerializer):
    nfc_card_state = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        model = CustomUser
        fields = ('id', 'phone_number', 'firstname', 'lastname', 'cash', 'user_type', 'is_active', 'nfc_card_state')
        read_only_fields = ('cash', 'is_active', 'nfc_card_state')

    def get_nfc_card_state(self, obj):
        # Only include NFC card state for client users
        if obj.user_type == UserType.CLIENT:
            try:
                return obj.nfc_card.is_active
            except NFCCard.DoesNotExist:
                return True
        return True


class UserExistsSerializer(serializers.Serializer):
    phone_number = PhoneNumberField(required=True)

    def validate_phone_number(self, value: str) -> str:
        if not CustomUser.objects.filter(phone_number=value, is_active=True).exists():
            raise serializers.ValidationError("Utilisateur non trouvé ou inactif.")
        return value


class BaseTransactionSerializer(serializers.Serializer):
    phone_number = PhoneNumberField(required=True)
    amount = serializers.IntegerField(min_value=100)  # Minimum 100 F CFA
    operator_code = serializers.ChoiceField(
        choices=[(service.serviceCode, service.serviceName) for service in MOMO_SERVICES],
        required=False
    )

    def validate_phone_number(self, value: str) -> str:
        try:
            user = CustomUser.objects.get(phone_number=value)
            if not user.is_active:
                raise serializers.ValidationError("Le compte utilisateur est inactif.")
            return value
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("Utilisateur non trouvé.")

    def validate_amount(self, value: int) -> int:
        if value > 1000000:  # Maximum 1,000,000 F CFA
            raise serializers.ValidationError("Montant maximum dépassé.")
        return value


class BaseNFCTransactionSerializer(serializers.Serializer):
    """Base serializer for NFC card transactions"""
    identifier = serializers.CharField(required=True, max_length=50)  # Identifiant unique de la carte (manufacturer ou virtual)
    amount = serializers.IntegerField(min_value=100)  # Minimum 100 F CFA

    def validate(self, data):
        """
        Validate that the identifier matches an active NFC card.
        """
        identifier = data['identifier']

        try:
            # Recherche de la carte en utilisant l'identifiant fourni
            nfc_card = NFCCard.objects.get(
                Q(physical_card_token=identifier) | Q(virtual_card_token=identifier)
            )

            # Vérifier que la carte est active
            if not nfc_card.is_active:
                raise serializers.ValidationError("La carte NFC est inactive.")

            # Vérifier que l'utilisateur associé à la carte est actif
            user = nfc_card.user
            if not user.is_active:
                raise serializers.ValidationError("Le compte utilisateur est inactif.")

            # Ajouter la carte validée aux données pour une utilisation ultérieure
            data['nfc_card'] = nfc_card

            return data

        except NFCCard.DoesNotExist:
            raise serializers.ValidationError({
                "identifier": "Identifiant de carte invalide."
            })

    def validate_amount(self, value: int) -> int:
        """
        Validate that the transaction amount is within acceptable limits.
        """
        if value > 1000000:  # Maximum 1,000,000 F CFA
            raise serializers.ValidationError("Montant maximum dépassé.")
        return value
class DepositSerializer(BaseNFCTransactionSerializer):
    transaction_type = serializers.ChoiceField(
        choices=[(TransactionType.DEPOSIT_CASH, "Dépôt en espèces")],
        default=TransactionType.DEPOSIT_CASH
    )


class DepositMobileMoneySerializer(BaseTransactionSerializer):
    '''operator_code = serializers.ChoiceField(
        choices=[(service.serviceCode, service.serviceName)
                for service in MOMO_SERVICES if service.type == "CASHOUT"],
        required=True
    )'''
    transaction_type = serializers.ChoiceField(
        choices=[(TransactionType.DEPOSIT_MOMO, "Dépôt Mobile Money")],
        default=TransactionType.DEPOSIT_MOMO
    )


class WithdrawSerializer(BaseNFCTransactionSerializer):
    transaction_type = serializers.ChoiceField(
        choices=[(TransactionType.WITHDRAW_CASH, "Retrait en espèces")],
        default=TransactionType.WITHDRAW_CASH
    )


class WithdrawMobileMoneySerializer(BaseTransactionSerializer):
    '''operator_code = serializers.ChoiceField(
        choices=[
            (service.serviceCode, service.serviceName)
            for service in MOMO_SERVICES
            if service.type == ServiceType.CASHOUT  # Compare against the ENUM
        ],
        required=True
    )'''
    transaction_type = serializers.ChoiceField(
        choices=[(TransactionType.WITHDRAW_MOMO, "Retrait Mobile Money")],
        default=TransactionType.WITHDRAW_MOMO
    )


class TransferSerializer(BaseTransactionSerializer):
    transaction_type = serializers.ChoiceField(
        choices=[(TransactionType.TRANSFER, "Transfert")],
        default=TransactionType.TRANSFER
    )


class PaymentSerializer(BaseNFCTransactionSerializer):
    transaction_type = serializers.ChoiceField(
        choices=[(TransactionType.PAYMENT, "Paiement")],
        default=TransactionType.PAYMENT
    )


class BaseTransactionHistorySerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    other_user = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()
    transaction_type = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    # Ajouter ces 2 champs avec des valeurs par défaut
    operator_code = serializers.SerializerMethodField()
    error_message = serializers.CharField(read_only=True, default=None)

    class Meta:
        fields = [
            'transaction_reference',
            'transaction_type',
            'amount',
            'timestamp',
            'other_user',
            'status',
            'operator_code',
            'error_message'
        ]
        read_only_fields = ['transaction_reference', 'timestamp', 'status']

    def get_amount(self, obj: Any) -> int:
        request = self.context.get('request')
        if request and request.user == obj.sender:
            return -obj.amount
        return obj.amount

    def get_timestamp(self, obj: Any) -> str:
        return timezone.localtime(obj.timestamp).strftime('%d %B %Y, %H:%M')

    def get_transaction_type(self, obj: Any) -> str:
        return obj.get_transaction_type_display()

    def get_status(self, obj: Any) -> str:
        return obj.get_status_display()

    def get_other_user(self, obj: Any) -> Optional[Dict[str, str]]:
        request = self.context.get('request')
        if not request:
            return None

        other_party = None
        if request.user == obj.sender:
            other_party = obj.receiver
        elif request.user == obj.receiver:
            other_party = obj.sender

        if not other_party:
            return None

        if isinstance(other_party, CustomUser):
            return {
                'phone_number': str(other_party.phone_number),
                'fullname': f"{other_party.firstname} {other_party.lastname}"
            }

        # Pour les transactions externes où other_party est un numéro de téléphone
        # Récupérer le nom de l'opérateur à partir du code d'opérateur
        operator_code = getattr(obj, 'operator_code', None)
        if operator_code:
            # Trouver le service et nettoyer le nom
            service = next(
                (s for s in MOMO_SERVICES if s.serviceCode == operator_code),
                None
            )

            if service:
                # Enlever les suffixes indésirables
                operator_name = service.serviceName
                operator_name = operator_name.replace(" Cashout SN", "") \
                    .replace(" Cashin SN", "") \
                    .replace(" Cashout", "") \
                    .replace(" Cashin", "")

                return {
                    'phone_number': str(other_party),
                    'fullname': f"Compte {operator_name}"
                }

            # Fallback si aucun opérateur n'est trouvé
        return {
            'phone_number': str(other_party),
            'fullname': "Compte Mobile Money"
        }


class InternalTransactionSerializer(BaseTransactionHistorySerializer):
    class Meta(BaseTransactionHistorySerializer.Meta):
        model = InternalTransaction

    def get_operator_code(self, obj):
        return None  # Les transactions internes n'ont pas d'opérateur




class ExternalDepositTransactionSerializer(BaseTransactionHistorySerializer):
    operator_code = serializers.SerializerMethodField()
    error_message = serializers.CharField(read_only=True)

    class Meta(BaseTransactionHistorySerializer.Meta):
        model = ExternalDepositTransaction
        fields = BaseTransactionHistorySerializer.Meta.fields + ['operator_code', 'error_message']

    def get_operator_code(self, obj: ExternalDepositTransaction) -> str:
        return next((service.serviceName for service in MOMO_SERVICES
                    if service.serviceCode == obj.operator_code), obj.operator_code)


class ExternalWithdrawalTransactionSerializer(BaseTransactionHistorySerializer):
    operator_code = serializers.SerializerMethodField()
    error_message = serializers.CharField(read_only=True)

    class Meta(BaseTransactionHistorySerializer.Meta):
        model = ExternalWithdrawalTransaction
        fields = BaseTransactionHistorySerializer.Meta.fields + ['operator_code', 'error_message']

    def get_operator_code(self, obj: ExternalWithdrawalTransaction) -> str:
        return next((service.serviceName for service in MOMO_SERVICES
                    if service.serviceCode == obj.operator_code), obj.operator_code)

class NFCCardLockSerializer(serializers.Serializer):
    card_activation_status = serializers.BooleanField(required=True)