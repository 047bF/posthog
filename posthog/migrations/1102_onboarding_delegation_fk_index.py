from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # Builds the FK index concurrently to avoid blocking reads/writes on posthog_user (large, hot table).
    atomic = False

    dependencies = [
        ("posthog", "1101_onboarding_delegation_fields"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="user",
            index=models.Index(
                fields=["onboarding_delegated_to_invite"],
                name="posthog_user_onboarding_deleg_idx",
            ),
        ),
    ]
