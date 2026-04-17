from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1100_add_subscription_summary_fields"),
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
