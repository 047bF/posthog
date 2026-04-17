from django.db import migrations, models


class Migration(migrations.Migration):
    # Builds the FK index concurrently so reads/writes on posthog_user (a large,
    # hot table) are not blocked during deploy. Uses the SeparateDatabaseAndState
    # + RunSQL pattern proven by earlier PostHog migrations (see e.g.
    # 0401_experiment_exposure_cohort). atomic=False is required for
    # CREATE INDEX CONCURRENTLY.

    atomic = False

    dependencies = [
        ("posthog", "1102_onboarding_delegation_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="user",
                    index=models.Index(
                        fields=["onboarding_delegated_to_invite"],
                        name="posthog_user_onboarding_deleg_idx",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'CREATE INDEX CONCURRENTLY IF NOT EXISTS "posthog_user_onboarding_deleg_idx" '
                        'ON "posthog_user" ("onboarding_delegated_to_invite_id");'
                    ),
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_user_onboarding_deleg_idx";',
                ),
            ],
        ),
    ]
