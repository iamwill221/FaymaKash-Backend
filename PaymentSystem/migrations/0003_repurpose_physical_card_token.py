# Repurpose physical_card_token: UUIDField → CharField(14) for DESFire UID

from django.db import migrations, models


def clear_uuid_tokens(apps, schema_editor):
    """Set all existing physical_card_token values to None since they were
    random UUIDs that don't correspond to real card UIDs."""
    NFCCard = apps.get_model('PaymentSystem', 'NFCCard')
    NFCCard.objects.all().update(physical_card_token=None)


class Migration(migrations.Migration):

    dependencies = [
        ('PaymentSystem', '0002_secure_hce_sdm'),
    ]

    operations = [
        # Step 1: Drop the unique constraint temporarily
        migrations.AlterField(
            model_name='nfccard',
            name='physical_card_token',
            field=models.CharField(
                max_length=36, null=True, blank=True, db_index=True,
            ),
        ),
        # Step 2: Clear old random UUID values
        migrations.RunPython(clear_uuid_tokens, migrations.RunPython.noop),
        # Step 3: Apply final field definition
        migrations.AlterField(
            model_name='nfccard',
            name='physical_card_token',
            field=models.CharField(
                max_length=14, null=True, blank=True, unique=True, db_index=True,
                help_text='DESFire EV3 card UID (7 bytes / 14 hex chars). Null for HCE-only users.',
            ),
        ),
    ]
