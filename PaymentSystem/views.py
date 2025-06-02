from datetime import datetime
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from djoser.views import UserViewSet
from .models import (
    CustomUser, InternalTransaction, ExternalDepositTransaction,
    ExternalWithdrawalTransaction, TransactionType, TransactionStatus, NFCCard, UserType
)
from .permissions import IsClient, IsManager
from .utils import send_otp_via_twilio, check_otp_via_twilio
from .serializers import (
    OtpRequestSerializer, OtpVerifySerializer, CustomUserCreateSerializer,
    InternalTransactionSerializer, ExternalDepositTransactionSerializer,
    ExternalWithdrawalTransactionSerializer, DepositSerializer,
    WithdrawSerializer, TransferSerializer, PaymentSerializer,
    DepositMobileMoneySerializer, WithdrawMobileMoneySerializer,
    UserExistsSerializer, NFCCardLockSerializer
)
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.db.models import Q


class CheckUserExistsView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = UserExistsSerializer(data=request.data)
        if serializer.is_valid():
            return Response({"exists": True}, status=status.HTTP_200_OK)
        return Response({"exists": False}, status=status.HTTP_404_NOT_FOUND)


class SendOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = OtpRequestSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            send_otp_via_twilio(phone_number)
            return Response({"message": "Code OTP envoyé avec succès"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = OtpVerifySerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            otp = serializer.validated_data['otp']
            if check_otp_via_twilio(phone_number, otp):
                return Response({"message": "Code OTP vérifié avec succès"}, status=status.HTTP_200_OK)
            return Response({"error": "Code OTP invalide"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PhoneNumberPincodeLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone_number = request.data.get('phone_number')
        pincode = request.data.get('pincode')

        user = authenticate(phone_number=phone_number, password=pincode)
        if user and user.is_active:
            refresh = RefreshToken.for_user(user)

            response_data = {
                'phone_number': str(user.phone_number),
                'user_type': user.user_type,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }

            if user.user_type == UserType.CLIENT:
                response_data['nfc_card_state'] = user.nfc_card.is_active if hasattr(user, 'nfc_card') else None

            return Response(response_data, status=status.HTTP_200_OK)
        return Response({'error': 'Identifiants invalides'}, status=status.HTTP_401_UNAUTHORIZED)


class CustomUserViewSet(UserViewSet):
    serializer_class = CustomUserCreateSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Create the user inside a transaction
            user = serializer.save()

            # If the user is a client, automatically create and assign an NFC card
            if user.user_type == UserType.CLIENT:
                nfc_card = NFCCard.objects.create(
                    user=user,
                    is_active=True,
                    last_accessed=datetime.now()
                )
                # Note: manufacturer_identifier will be assigned when the physical card
                # is actually paired with the account

            # Generate authentication tokens
            refresh = RefreshToken.for_user(user)

            # Prepare the response data
            response_data = {
                'phone_number': str(user.phone_number),
                'user_type': user.user_type,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'nfc_card_state': nfc_card.is_active if hasattr(user, 'nfc_card') else None
            }

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            # If anything fails, the transaction will be rolled back
            return Response(
                {'error': f'Failed to create user: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class BaseTransactionView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            receiver = CustomUser.objects.get(phone_number=serializer.validated_data['phone_number'])
            operator_code = serializer.validated_data.get('operator_code')

            response = self.perform_transaction(
                sender=request.user,
                receiver=receiver,
                amount=serializer.validated_data['amount'],
                operator_code=operator_code
            )

            if response:
                return Response(response)

            return Response({"message": "Transaction effectuée avec succès"}, status=status.HTTP_201_CREATED)

        except CustomUser.DoesNotExist:
            raise ValidationError("Destinataire non trouvé.")
        except ValidationError as e:
            raise ValidationError(str(e))
        except Exception as e:
            raise ValidationError(f"Erreur lors de la transaction: {str(e)}")

    def perform_transaction(self, sender, receiver, amount, operator_code=None):
        raise NotImplementedError

class BaseNFCTransactionView(generics.CreateAPIView):
    """Base view for NFC card transactions"""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Get the NFC card (validation already done in serializer)
            nfc_card = serializer.validated_data['nfc_card']
            receiver = nfc_card.user

            # Additional validation for active status (although already checked in serializer)
            if not nfc_card.is_active:
                raise ValidationError("La carte NFC du client est désactivée. La transaction ne peut pas être effectuée.")

            # Update last accessed timestamp
            nfc_card.last_accessed = timezone.now()
            nfc_card.save()

            # Perform the transaction based on the specific transaction type
            response = self.perform_transaction(
                sender=request.user,
                receiver=receiver,
                amount=serializer.validated_data['amount'],
            )

            if response:
                return Response(response)

            return Response({
                "message": "Transaction effectuée avec succès",
                "timestamp": nfc_card.last_accessed
            }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            raise ValidationError(str(e))
        except Exception as e:
            raise ValidationError(f"Erreur lors de la transaction: {str(e)}")

class DepositView(BaseNFCTransactionView):
    serializer_class = DepositSerializer
    permission_classes = [IsManager]

    def perform_transaction(self, sender, receiver, amount, operator_code=None):
        sender.deposit(receiver, amount)


class WithdrawView(BaseNFCTransactionView):
    serializer_class = WithdrawSerializer
    permission_classes = [IsManager]

    def perform_transaction(self, sender, receiver, amount, operator_code=None):
        sender.withdraw(receiver, amount)

class PaymentView(BaseNFCTransactionView):
    serializer_class = PaymentSerializer
    permission_classes = [IsManager]

    def perform_transaction(self, sender, receiver, amount, operator_code=None):
        sender.payment(receiver, amount)

class TransferView(BaseTransactionView):
    serializer_class = TransferSerializer
    permission_classes = [IsAuthenticated]

    def perform_transaction(self, sender, receiver, amount, operator_code=None):
        sender.transfer(receiver, amount)



class DepositMobileMoneyView(BaseTransactionView):
    serializer_class = DepositMobileMoneySerializer
    permission_classes = [IsAuthenticated]

    def perform_transaction(self, sender, receiver, amount, operator_code):
        if not operator_code:
            raise ValidationError("Code opérateur requis pour les transactions mobile money.")
        return sender.deposit_momo(receiver, amount, operator_code)


class WithdrawMobileMoneyView(BaseTransactionView):
    serializer_class = WithdrawMobileMoneySerializer
    permission_classes = [IsAuthenticated]

    def perform_transaction(self, sender, receiver, amount, operator_code):
        if not operator_code:
            raise ValidationError("Code opérateur requis pour les transactions mobile money.")
        return sender.withdraw_momo(receiver, amount, operator_code)



class TransactionHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        # Get all transactions where user is sender or receiver
        internal_transactions = InternalTransaction.objects.filter(
            Q(sender=user) | Q(receiver=user)
        )

        external_deposits = ExternalDepositTransaction.objects.filter(
            receiver=user
        )

        external_withdrawals = ExternalWithdrawalTransaction.objects.filter(
            sender=user
        )

        # Combine and sort all transactions by timestamp
        return sorted(
            list(internal_transactions) +
            list(external_deposits) +
            list(external_withdrawals),
            key=lambda x: x.timestamp,
            reverse=True
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = []

        for transaction in queryset:
            # Determine the correct serializer based on transaction type
            if isinstance(transaction, InternalTransaction):
                serializer_class = InternalTransactionSerializer
            elif isinstance(transaction, ExternalDepositTransaction):
                serializer_class = ExternalDepositTransactionSerializer
            elif isinstance(transaction, ExternalWithdrawalTransaction):
                serializer_class = ExternalWithdrawalTransactionSerializer
            else:
                continue  # Skip unknown types or handle error

            serializer = serializer_class(transaction, context={'request': request})
            data.append(serializer.data)

        return Response(data)

class DexchangeCallbackView(APIView):
    permission_classes = [AllowAny]  # Adjust permissions as needed (e.g., IP verification)

    def post(self, request):
        data = request.data
        print("------------------------- This is the data -------------------------")
        print(data)

        # Extract fields from the request data
        transaction_id = data.get("externalTransactionId")
        new_status = data.get("STATUS", "").lower()  # 'completed', 'failed', etc.
        if new_status == "success":
            new_status = "completed"
        print("The new status from dexchange is {}".format(new_status))
        external_ref = data.get("id")
        error = data.get("error")
        amount = data.get("AMOUNT")
        fee = data.get("FEE")
        phone_number = data.get("PHONE_NUMBER")
        custom_data = data.get("CUSTOM_DATA")
        completed_at = data.get("COMPLETED_AT")
        balance = data.get("BALANCE")
        previous_balance = data.get("PREVIOUS_BALANCE")
        current_balance = data.get("CURRENT_BALANCE")

        # Find the transaction
        transaction = (
            ExternalDepositTransaction.objects.filter(transaction_reference=transaction_id).first()
            or ExternalWithdrawalTransaction.objects.filter(transaction_reference=transaction_id).first()
        )

        if not transaction:
            return Response({"error": "Transaction not found"}, status=404)

        # Update the transaction status and other fields
        transaction.status = new_status
        transaction.external_reference = external_ref
        transaction.error_message = error
        transaction.save()

        # Update balance if the transaction is completed
        if new_status == TransactionStatus.COMPLETED:
            if isinstance(transaction, ExternalDepositTransaction):
                # Credit the receiver
                transaction.receiver.cash += transaction.amount
                transaction.receiver.save()

            elif isinstance(transaction, ExternalWithdrawalTransaction):
                # Deduction has already been made at initiation
                pass  # No additional action needed

        # Refund if the transaction failed for withdrawals
        elif new_status == TransactionStatus.FAILED:
            if isinstance(transaction, ExternalWithdrawalTransaction):
                transaction.sender.cash += transaction.amount
                transaction.sender.save()

        # Prepare the response
        response_data = {
            "id": external_ref,
            "externalTransactionId": transaction_id,
            "transactionType": "deposit" if isinstance(transaction, ExternalDepositTransaction) else "withdrawal",
            "AMOUNT": amount,
            "FEE": fee,
            "PHONE_NUMBER": phone_number,
            "STATUS": new_status.upper(),
            "CUSTOM_DATA": custom_data,
            "COMPLETED_AT": completed_at,
            "BALANCE": balance,
            "PREVIOUS_BALANCE": previous_balance,
            "CURRENT_BALANCE": current_balance,
        }

        return Response(response_data, status=200)

def success_page(request):
    return render(request, 'transactions/success.html')

def failure_page(request):
    return render(request, 'transactions/failure.html')


class NFCCardLockView(APIView):
    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request):
        if request.user.user_type != UserType.CLIENT:
            return Response(
                {"error": "Seuls les clients peuvent gérer leur carte NFC"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = NFCCardLockSerializer(data=request.data)

        if serializer.is_valid():
            try:
                card = request.user.nfc_card
                card_activation_status = serializer.validated_data['card_activation_status']

                if card_activation_status:
                    card.unlock_card()
                    message = "Votre carte NFC a été débloquée avec succès"
                else:
                    card.lock_card()
                    message = "Votre carte NFC a été bloquée avec succès"

                return Response({
                    'message': message,
                    'card_activation_status': card.is_active,
                }, status=status.HTTP_200_OK)

            except NFCCard.DoesNotExist:
                return Response(
                    {"error": "Aucune carte NFC associée à votre compte"},
                    status=status.HTTP_404_NOT_FOUND
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdateVirtualCardIdentifierView(APIView):
    permission_classes = [IsAuthenticated, IsClient]

    def post(self, request):
        try:
            # Mettre à jour l'UID HCE de la carte associée à l'utilisateur
            nfc_card = request.user.nfc_card
            new_virtual_card_identifier = nfc_card.update_virtual_card_token()
            return Response({
                "virtual_card_identifier": new_virtual_card_identifier
            }, status=status.HTTP_200_OK)
        except NFCCard.DoesNotExist:
            return Response({"error": "Aucune carte NFC trouvée"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)