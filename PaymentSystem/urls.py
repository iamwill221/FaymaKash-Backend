from django.urls import path, include
from .views import (
    SendOtpView,
    VerifyOtpView,
    PhoneNumberPincodeLoginView,
    CustomUserViewSet,
    CheckUserExistsView,
    DepositView,
    WithdrawView,
    TransferView,
    PaymentView,
    TransactionHistoryView,  # Updated from UserTransactionsView to TransactionHistoryView
    DepositMobileMoneyView,
    WithdrawMobileMoneyView, DexchangeCallbackView, success_page, failure_page, NFCCardLockView,
    UpdateVirtualCardIdentifierView,
)

urlpatterns = [
    # Authentication endpoints
    path('auth/send-otp/', SendOtpView.as_view(), name='send-otp'),
    path('auth/verify-otp/', VerifyOtpView.as_view(), name='verify-otp'),
    path('auth/check-user/', CheckUserExistsView.as_view(), name='check-user'),
    path('auth/login/', PhoneNumberPincodeLoginView.as_view(), name='login'),

    # User registration endpoint (using Djoser's CustomUserViewSet)
    path('auth/users/', CustomUserViewSet.as_view({'post': 'create'}), name='user-create'),

    # Include Djoser's default URLs for authentication (JWT, password reset, etc.)
    path('auth/', include('djoser.urls')),
    path('auth/', include('djoser.urls.jwt')),

    # Transaction endpoints
    path('transactions/', include([
        path('', TransactionHistoryView.as_view(), name='user-transactions'),  # Updated to TransactionHistoryView
        path('deposit/', DepositView.as_view(), name='deposit'),  # Deposit funds
        path('withdraw/', WithdrawView.as_view(), name='withdraw'),  # Withdraw funds
        path('transfer/', TransferView.as_view(), name='transfer'),  # Transfer funds
        path('payment/', PaymentView.as_view(), name='payment'),  # Make a payment
        path('deposit_momo/', DepositMobileMoneyView.as_view(), name='deposit-momo'),  # Mobile money deposit
        path('withdraw_momo/', WithdrawMobileMoneyView.as_view(), name='withdraw-momo'),  # Mobile money withdrawal
        path('callback/dexchange/', DexchangeCallbackView.as_view(), name='dexchange-callback'),
        path('success/', success_page, name='success'),
        path('failure/', failure_page, name='failure'),
    ])),

    # NFC endpoints
    path('nfc/', include([
        path('manage/', NFCCardLockView.as_view(), name='nfc-card-manage'),
        path('update_vcard_id/', UpdateVirtualCardIdentifierView.as_view(), name='update_vcard_id'),
    ])),
    ]