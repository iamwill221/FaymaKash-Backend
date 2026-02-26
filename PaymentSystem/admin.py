from django.contrib import admin
from .models import CustomUser, InternalTransaction, ExternalDepositTransaction, ExternalWithdrawalTransaction, NFCCard, UsedNonce

@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'firstname', 'lastname', 'user_type', 'cash', 'is_active')
    search_fields = ('phone_number', 'firstname', 'lastname')
    list_filter = ('user_type', 'is_active')
    ordering = ('phone_number',)
    readonly_fields = ('date_joined', 'last_login')  # Ajout de champs en lecture seule
    fieldsets = (
        (None, {
            'fields': ('phone_number', 'firstname', 'lastname', 'user_type', 'cash', 'is_active')
        }),
        ('Permissions', {
            'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {
            'fields': ('date_joined', 'last_login'),
        }),
    )

@admin.register(InternalTransaction)
class InternalTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_type', 'amount', 'sender', 'receiver', 'status', 'timestamp')
    search_fields = ('sender__phone_number', 'receiver__phone_number', 'transaction_reference')
    list_filter = ('transaction_type', 'status', 'timestamp')
    readonly_fields = ('timestamp', 'transaction_reference')  # Ajout de champs en lecture seule
    fieldsets = (
        (None, {
            'fields': ('transaction_type', 'amount', 'sender', 'receiver', 'status')
        }),
        ('Metadata', {
            'fields': ('timestamp', 'transaction_reference'),
        }),
    )

@admin.register(ExternalDepositTransaction)
class ExternalDepositTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_type', 'amount', 'sender', 'receiver', 'operator_code', 'status', 'timestamp')
    search_fields = ('sender', 'receiver__phone_number', 'transaction_reference')
    list_filter = ('operator_code', 'status', 'timestamp')
    readonly_fields = ('timestamp', 'transaction_reference', 'external_reference', 'error_message')  # Ajout de champs en lecture seule
    fieldsets = (
        (None, {
            'fields': ('transaction_type', 'amount', 'sender', 'receiver', 'operator_code', 'status')
        }),
        ('External Data', {
            'fields': ('external_reference', 'error_message'),
        }),
        ('Metadata', {
            'fields': ('timestamp', 'transaction_reference'),
        }),
    )

@admin.register(ExternalWithdrawalTransaction)
class ExternalWithdrawalTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_type', 'amount', 'sender', 'receiver', 'operator_code', 'status', 'timestamp')
    search_fields = ('sender__phone_number', 'receiver', 'transaction_reference')
    list_filter = ('operator_code', 'status', 'timestamp')
    readonly_fields = ('timestamp', 'transaction_reference', 'external_reference', 'error_message')  # Ajout de champs en lecture seule
    fieldsets = (
        (None, {
            'fields': ('transaction_type', 'amount', 'sender', 'receiver', 'operator_code', 'status')
        }),
        ('External Data', {
            'fields': ('external_reference', 'error_message'),
        }),
        ('Metadata', {
            'fields': ('timestamp', 'transaction_reference'),
        }),
    )

@admin.register(NFCCard)
class NFCCardAdmin(admin.ModelAdmin):
    list_display = ('user', 'physical_card_token', 'is_active', 'last_accessed', 'last_sdm_counter')
    search_fields = ('physical_card_token', 'user__phone_number', 'user__firstname', 'user__lastname')
    list_filter = ('is_active',)
    readonly_fields = ('last_accessed', 'virtual_card_token', 'last_sdm_counter')
    fieldsets = (
        (None, {
            'fields': ('physical_card_token', 'virtual_card_token', 'user', 'is_active')
        }),
        ('DESFire EV3 SDM', {
            'fields': ('sdm_aes_key', 'last_sdm_counter'),
        }),
        ('Metadata', {
            'fields': ('last_accessed',),
        }),
    )


@admin.register(UsedNonce)
class UsedNonceAdmin(admin.ModelAdmin):
    list_display = ('nonce', 'used_at')
    search_fields = ('nonce',)
    readonly_fields = ('nonce', 'used_at')