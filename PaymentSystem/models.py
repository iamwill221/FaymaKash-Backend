import random
import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.db.models import F, Max
from phonenumber_field.modelfields import PhoneNumberField
from enum import Enum
from django.core.exceptions import ValidationError
from django.utils import timezone
from typing import Optional, Union
from decimal import Decimal
from .transactions_momo import dexchange_api, TransactionError, MOMO_SERVICES
import logging

logger = logging.getLogger(__name__)


class UserType(models.TextChoices):
    CLIENT = 'client', 'Client'
    MANAGER = 'manager', 'Manager'
    ADMIN = 'admin', 'Admin'


class TransactionType(models.TextChoices):
    DEPOSIT_CASH = 'deposit_cash', 'Dépôt en espèces'
    DEPOSIT_MOMO = 'deposit_momo', 'Dépôt'
    WITHDRAW_CASH = 'withdraw_cash', 'Retrait en espèces'
    WITHDRAW_MOMO = 'withdraw_momo', 'Retrait'
    PAYMENT = 'payment', 'Paiement marchand'
    TRANSFER = 'transfer', 'Transfert'


class TransactionStatus(models.TextChoices):
    PENDING = 'pending', 'En attente'
    PROCESSING = 'processing', 'En cours'
    COMPLETED = 'completed', 'Terminé'
    FAILED = 'failed', 'Échoué'


class OperatorCode(models.TextChoices):
    OM_SN_CASHIN = 'OM_SN_CASHIN', 'Orange Money'
    OM_SN_CASHOUT = 'OM_SN_CASHOUT', 'Orange Money'
    WAVE_SN_CASHIN = 'WAVE_SN_CASHIN', 'Wave'
    WAVE_SN_CASHOUT = 'WAVE_SN_CASHOUT', 'Wave'
    FM_SN_CASHIN = 'FM_SN_CASHIN', 'Free Money'
    FM_SN_CASHOUT = 'FM_SN_CASHOUT', 'Free Money'
    WIZALL_SN_CASHIN = 'WIZALL_SN_CASHIN', 'Wizall'
    WIZALL_SN_CASHOUT = 'WIZALL_SN_CASHOUT', 'Wizall'


class TransactionValidationMixin:
    """Mixin providing common transaction validation methods."""

    @staticmethod
    def validate_amount(amount: int) -> None:
        """Validate transaction amount."""
        if amount <= 0:
            raise ValidationError("Le montant doit être positif.")
        if amount > 1000000:  # Example maximum limit
            raise ValidationError("Le montant dépasse la limite autorisée.")

    @staticmethod
    def validate_different_users(sender: 'CustomUser', receiver: 'CustomUser') -> None:
        """Validate that sender and receiver are different users."""
        if sender == receiver:
            raise ValidationError("L'expéditeur et le destinataire ne peuvent pas être identiques.")

    @staticmethod
    def validate_sufficient_funds(user: 'CustomUser', amount: int) -> None:
        """Validate that user has sufficient funds."""
        if user.cash < amount:
            raise ValidationError("Solde insuffisant pour cette transaction.")

    @staticmethod
    def validate_manager_permission(user: 'CustomUser') -> None:
        """Validate that user has manager permissions."""
        if user.user_type != UserType.MANAGER:
            raise ValidationError("Seul un manager peut effectuer cette action.")


class CustomUserManager(BaseUserManager):
    def create_user(self, phone_number: str, password: Optional[str] = None, **extra_fields) -> 'CustomUser':
        if not phone_number:
            raise ValueError("Le numéro de téléphone est obligatoire")

        if extra_fields.get('user_type') == UserType.MANAGER.value:
            extra_fields.setdefault('cash', 500000)

        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number: str, password: Optional[str] = None, **extra_fields) -> 'CustomUser':
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('user_type', UserType.ADMIN.value)
        return self.create_user(phone_number, password, **extra_fields)


class CustomUser(AbstractUser, TransactionValidationMixin):
    phone_number = PhoneNumberField(unique=True)
    firstname = models.CharField(max_length=30)
    lastname = models.CharField(max_length=30)
    cash = models.IntegerField(default=0)
    username = None
    user_type = models.CharField(max_length=10, choices=UserType.choices, default=UserType.CLIENT)
    is_active = models.BooleanField(default=True)

    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['firstname', 'lastname']

    objects = CustomUserManager()

    def __str__(self) -> str:
        return f"{self.firstname} {self.lastname} ({self.phone_number})"

    def deposit(self, other_user: 'CustomUser', amount: int,
                transaction_type: str = TransactionType.DEPOSIT_CASH) -> None:
        """
        Deposit funds to recipient's account.

        Args:
            other_user: Recipient user
            amount: Amount to deposit
            transaction_type: Type of transaction
        """
        self.validate_manager_permission(self)
        self.validate_amount(amount)
        self.validate_sufficient_funds(self, amount)
        self.validate_different_users(self, other_user)

        with transaction.atomic():
            CustomUser.objects.filter(pk=self.pk).update(cash=F('cash') + amount)
            CustomUser.objects.filter(pk=other_user.pk).update(cash=F('cash') - amount)

            InternalTransaction.objects.create(
                transaction_type=transaction_type,
                amount=amount,
                sender=self,
                receiver=other_user,
                status=TransactionStatus.COMPLETED,
            )

            logger.info(f"Deposit completed: {amount} from {self} to {other_user}")

    def withdraw(self, other_user: 'CustomUser', amount: int,
                 transaction_type: str = TransactionType.WITHDRAW_CASH) -> None:
        """
        Withdraw funds from user's account.

        Args:
            other_user: User to withdraw from
            amount: Amount to withdraw
            transaction_type: Type of transaction
        """
        self.validate_manager_permission(self)
        self.validate_amount(amount)
        self.validate_sufficient_funds(other_user, amount)
        self.validate_different_users(self, other_user)

        with transaction.atomic():
            CustomUser.objects.filter(pk=self.pk).update(cash=F('cash') - amount)
            CustomUser.objects.filter(pk=other_user.pk).update(cash=F('cash') + amount)

            InternalTransaction.objects.create(
                transaction_type=transaction_type,
                amount=amount,
                sender=other_user,
                receiver=self,
                status=TransactionStatus.COMPLETED,
            )

            logger.info(f"Withdrawal completed: {amount} from {other_user} to {self}")

    def transfer(self, other_user: 'CustomUser', amount: int) -> None:
        """
        Transfer funds to another user.

        Args:
            other_user: Recipient user
            amount: Amount to transfer
        """
        self.validate_amount(amount)
        self.validate_sufficient_funds(self, amount)
        self.validate_different_users(self, other_user)

        with transaction.atomic():
            CustomUser.objects.filter(pk=self.pk).update(cash=F('cash') - amount)
            CustomUser.objects.filter(pk=other_user.pk).update(cash=F('cash') + amount)

            InternalTransaction.objects.create(
                transaction_type=TransactionType.TRANSFER,
                amount=amount,
                sender=self,
                receiver=other_user,
                status=TransactionStatus.COMPLETED,
            )

            logger.info(f"Transfer completed: {amount} from {self} to {other_user}")

    def payment(self, other_user: 'CustomUser', amount: int) -> None:
        """
        Process a payment transaction where the manager (self) receives funds from another user.

        Args:
            other_user: The user making the payment.
            amount: The amount to be transferred.
        """

        self.validate_amount(amount)
        self.validate_sufficient_funds(self, amount)
        self.validate_different_users(self, other_user)

        with transaction.atomic():
            CustomUser.objects.filter(pk=self.pk).update(cash=F('cash') + amount)
            CustomUser.objects.filter(pk=other_user.pk).update(cash=F('cash') - amount)

            InternalTransaction.objects.create(
                transaction_type=TransactionType.PAYMENT,
                amount=amount,
                sender=other_user,
                receiver=self,
                status=TransactionStatus.COMPLETED,
            )

            logger.info(f"Payment completed: {amount} from {self} to merchant {other_user}")

    def deposit_momo(self, other_user: 'CustomUser', amount: int, operator_code: str) -> None:
        """
        Deposit funds from mobile money account.

        Args:
            other_user: User receiving deposit
            amount: Amount to deposit
            operator_code: Mobile money operator code
        """
        if not operator_code:
            raise ValidationError("Le code opérateur est obligatoire.")

        self.validate_amount(amount)

        with transaction.atomic():
            transaction_record = ExternalDepositTransaction.objects.create(
                transaction_type=TransactionType.DEPOSIT_MOMO,
                amount=amount,
                sender=str(other_user.phone_number),
                receiver=self,
                operator_code=operator_code,
                status=TransactionStatus.PENDING,  # Statut initial
            )

            try:
                response = dexchange_api.send_transaction_payload(
                    external_transaction_id=transaction_record.transaction_reference,
                    service_code=operator_code,
                    amount=amount,
                    number=str(other_user.phone_number),
                )

                if response.get('success') == True:
                    transaction_record.status = TransactionStatus.PROCESSING
                    transaction_record.external_reference = response.get('transactionId')
                    transaction_record.save()  # Pas de mise à jour de cash ici !
                    logger.info(f"Mobile money deposit initiated: {amount} from {other_user}")
                    return response
                else:
                    raise TransactionError(f"Transaction refusée: {response.get('message')}")

            except (TransactionError, Exception) as e:
                transaction_record.status = TransactionStatus.FAILED
                transaction_record.error_message = str(e)
                transaction_record.save()
                logger.error(f"Mobile money deposit failed: {str(e)}")
                raise ValidationError(f"La transaction a échoué: {str(e)}")

    def withdraw_momo(self, other_user: 'CustomUser', amount: int, operator_code: str) -> None:
        """
        Withdraw funds to mobile money account.

        Args:
            other_user: User withdrawing funds
            amount: Amount to withdraw
            operator_code: Mobile money operator code
        """
        if not operator_code:
            raise ValidationError("Le code opérateur est obligatoire.")

        self.validate_amount(amount)
        self.validate_sufficient_funds(self, amount)

        with transaction.atomic():
            # Vérifier et bloquer le montant
            self.validate_sufficient_funds(self, amount)
            CustomUser.objects.filter(pk=self.pk).update(cash=F('cash') - amount)  # Déduction immédiate

            transaction_record = ExternalWithdrawalTransaction.objects.create(
                transaction_type=TransactionType.WITHDRAW_MOMO,
                amount=amount,
                sender=self,
                receiver=str(other_user.phone_number),
                operator_code=operator_code,
                status=TransactionStatus.PENDING,
            )

            try:
                response = dexchange_api.send_transaction_payload(
                    external_transaction_id=transaction_record.transaction_reference,
                    service_code=operator_code,
                    amount=amount,
                    number=str(other_user.phone_number),
                )

                if response.get('Status') == 'SUCCESS':
                    transaction_record.status = TransactionStatus.COMPLETED
                    transaction_record.external_reference = response.get('transactionId')
                    transaction_record.save()  # Pas de mise à jour de cash ici !
                    logger.info(f"Mobile money deposit initiated: {amount} from {other_user}")
                    return response
                elif response.get('Status') == 'PENDING':
                    transaction_record.status = TransactionStatus.PROCESSING
                    transaction_record.external_reference = response.get('transactionId')
                    transaction_record.save()  # Pas de mise à jour de cash ici !
                    logger.info(f"Mobile money deposit initiated: {amount} from {other_user}")
                    return response
                else:
                    raise TransactionError(f"Transaction refusée: {response.get('message')}")

            except (TransactionError, Exception) as e:
                # Rembourser si l'appel API échoue
                CustomUser.objects.filter(pk=self.pk).update(cash=F('cash') + amount)
                transaction_record.status = TransactionStatus.FAILED
                transaction_record.error_message = str(e)
                transaction_record.save()
                logger.error(f"Mobile money withdrawal failed: {str(e)}")
                raise ValidationError(f"La transaction a échoué: {str(e)}")


class Transaction(models.Model):
    """Base abstract transaction model."""

    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    transaction_reference = models.CharField(max_length=50, unique=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.get_transaction_type_display()} - {self.amount} ({self.timestamp})"

    def save(self, *args, **kwargs) -> None:
        if not self.transaction_reference:
            self.transaction_reference = self.generate_transaction_reference()
        super().save(*args, **kwargs)

    def generate_transaction_reference(self) -> str:
        today = timezone.now().strftime("%Y-%m-%d")
        max_sequence = self.__class__.objects.filter(
            transaction_reference__startswith=f"FKash-{today}"
        ).aggregate(Max('transaction_reference'))['transaction_reference__max']

        sequence = int(max_sequence.split('-')[-1]) + 1 if max_sequence else 1
        return f"FKash-{today}-{sequence:05d}{random.randint(1000, 9999)}"


class InternalTransaction(Transaction):
    """Model for transactions between system users."""

    sender = models.ForeignKey(CustomUser, related_name='sent_internal_transactions',
                               on_delete=models.CASCADE)
    receiver = models.ForeignKey(CustomUser, related_name='received_internal_transactions',
                                 on_delete=models.CASCADE)


class ExternalTransaction(Transaction):
    """Base model for external transactions (mobile money)."""

    operator_code = models.CharField(max_length=50,
                                     choices=[(service.serviceCode, service.serviceName) for service in MOMO_SERVICES])
    external_reference = models.CharField(max_length=100, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        abstract = True

    def update_status_from_callback(self, status: str, transaction_id: str = None, error: str = None) -> None:
        """
        Update transaction status from callback.

        Args:
            status: New status
            transaction_id: External transaction ID
            error: Error message if any
        """
        self.status = status
        if transaction_id:
            self.external_reference = transaction_id
        if error:
            self.error_message = error
        self.save()


class ExternalDepositTransaction(ExternalTransaction):
    """Model for mobile money deposit transactions."""

    sender = PhoneNumberField()
    receiver = models.ForeignKey(CustomUser, related_name='received_external_transactions',
                                 on_delete=models.CASCADE)


class ExternalWithdrawalTransaction(ExternalTransaction):
    """Model for mobile money withdrawal transactions."""

    sender = models.ForeignKey(CustomUser, related_name='sent_external_transactions',
                               on_delete=models.CASCADE)
    receiver = PhoneNumberField()


class NFCCard(models.Model):
    physical_card_token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)  # Numéro de série unique, 14 caractères hexadécimaux
    virtual_card_token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    user = models.OneToOneField('CustomUser', on_delete=models.CASCADE,
                                related_name='nfc_card')  # Un seul utilisateur par carte
    is_active = models.BooleanField(default=True)  # Statut de la carte (active/inactive)
    last_accessed = models.DateTimeField(null=True, blank=True)  # Dernière utilisation de la carte

    def update_virtual_card_token(self):
        """Met à jour l'identifiant de la carte virtuelle avec un nouveau UUID"""
        self.virtual_card_token = uuid.uuid4()  # Assign a new UUID to the virtual_card_token
        self.last_accessed = timezone.now()
        self.save()
        return self.virtual_card_token  # Return the updated virtual_card_token

    def lock_card(self):
        """Method to block the NFC card"""
        self.is_active = False
        self.save()

    def unlock_card(self):
        """Method to unblock the NFC card"""
        self.is_active = True
        self.save()

    def __str__(self):
        return f"NFC Card {self.physical_card_token} ({self.physical_card_token}) for {self.user.username}"
