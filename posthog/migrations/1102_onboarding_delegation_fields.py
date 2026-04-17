from django.db import migrations, models


class Migration(migrations.Migration):
    # Adding new nullable columns + a default-false boolean to posthog_user and
    # posthog_organizationinvite. All ops are metadata-only in PostgreSQL 11+, so
    # this is safe under lock_timeout. The FK's concurrent index ships in 1103.

    dependencies = [
        ("posthog", "1101_activitylog_client"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationinvite",
            name="is_setup_delegation",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_skipped_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_skipped_reason",
            field=models.CharField(max_length=32, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_delegated_to_invite",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=models.SET_NULL,
                related_name="delegating_users",
                to="posthog.organizationinvite",
                db_index=False,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="onboarding_delegation_accepted_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
