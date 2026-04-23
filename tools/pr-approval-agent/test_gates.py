"""Tests for deny-list pattern matching in gates.py."""

import pytest

from gates import detect_deny_categories
from noop_migrations import detect_noop_migration_files, migration_bookkeeping_files_for

# ── False positives that should NOT trigger ──────────────────────


@pytest.mark.parametrize(
    "files, subject",
    [
        pytest.param(
            [
                "frontend/src/queries/nodes/InsightViz/EditorFilters/SessionAnalysisWarning.tsx",
                "frontend/src/queries/nodes/InsightViz/EditorFilters/SuggestionBanner.tsx",
                "frontend/src/queries/nodes/InsightViz/EditorFilters/EditorFilterItems.tsx",
            ],
            "chore(insights): extract SessionAnalysisWarning, SuggestionBanner, EditorFilterItems",
            id="session-analysis-warning-component",
        ),
        pytest.param(
            ["frontend/src/lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic.ts"],
            "fix(taxonomic-filter): scope recents localStorage key by team id",
            id="localstorage-key-in-title",
        ),
        pytest.param(
            ["frontend/src/lib/utils/tokenizer.ts"],
            "fix: improve tokenizer performance",
            id="tokenizer-not-auth-token",
        ),
        pytest.param(
            ["frontend/src/scenes/session-recordings/SessionRecordingPlayer.tsx"],
            "feat(replay): add session recording playback controls",
            id="session-recording-not-auth",
        ),
        pytest.param(
            ["frontend/src/lib/components/KeyboardShortcut.tsx"],
            "fix: keyboard shortcut not working",
            id="keyboard-not-crypto-key",
        ),
        pytest.param(
            ["frontend/src/lib/hooks/useRoutingLogic.ts"],
            "fix: routing logic for dashboard",
            id="routing-logic-not-infra",
        ),
    ],
)
def test_no_false_positive(files: list[str], subject: str) -> None:
    assert detect_deny_categories(files, subject) == []


# ── True positives that SHOULD trigger ───────────────────────────


@pytest.mark.parametrize(
    "files, subject, expected_category",
    [
        pytest.param(
            ["posthog/api/authentication.py"],
            "fix: auth flow redirect",
            "auth",
            id="auth-file-and-title",
        ),
        pytest.param(
            ["posthog/api/login.py"],
            "fix: login endpoint",
            "auth",
            id="login-endpoint",
        ),
        pytest.param(
            ["posthog/models/oauth_config.py"],
            "feat: add oauth config",
            "auth",
            id="oauth-config",
        ),
        pytest.param(
            ["posthog/api/auth/session_token.py"],
            "fix: session token refresh",
            "auth",
            id="auth-session-token-path",
        ),
        pytest.param(
            ["posthog/crypto/encrypt.py"],
            "feat: add encryption support",
            "crypto_secrets",
            id="encryption-file",
        ),
        pytest.param(
            ["posthog/settings/.env.example"],
            "chore: update env example",
            "crypto_secrets",
            id="dot-env-file",
        ),
        pytest.param(
            ["posthog/api/api_key.py"],
            "fix: api key rotation",
            "crypto_secrets",
            id="api-key-file",
        ),
        pytest.param(
            ["posthog/models/secret_key_store.py"],
            "feat: secret key management",
            "crypto_secrets",
            id="secret-key-file",
        ),
        pytest.param(
            ["posthog/migrations/0400_add_column.py"],
            "feat: add new column",
            "migrations",
            id="migration-file",
        ),
        pytest.param(
            [".github/workflows/ci.yml"],
            "chore(ci): update workflow",
            "infra_cicd",
            id="github-workflow",
        ),
        pytest.param(
            ["posthog/billing/stripe_webhook.py"],
            "fix: billing webhook",
            "billing",
            id="billing-file",
        ),
        pytest.param(
            ["package.json"],
            "chore: update dependencies",
            "deps_toolchain",
            id="package-json",
        ),
        pytest.param(
            ["pyproject.toml"],
            "chore: bump version",
            "deps_toolchain",
            id="pyproject-toml",
        ),
    ],
)
def test_true_positive(files: list[str], subject: str, expected_category: str) -> None:
    result = detect_deny_categories(files, subject)
    assert expected_category in result, f"Expected '{expected_category}' in {result}"


def test_detect_noop_choice_migration() -> None:
    migration_content = """
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.AlterField(
            model_name="integration",
            name="kind",
            field=models.CharField(
                choices=[
                    ("slack", "Slack"),
                    ("postgresql", "Postgresql"),
                ],
                max_length=32,
            ),
        ),
    ]
"""
    base_model_content = """
from django.db import models


class Integration(models.Model):
    class IntegrationKind(models.TextChoices):
        SLACK = "slack"

    kind = field_access_control(
        models.CharField(max_length=32, choices=IntegrationKind.choices),
        "project",
        "admin",
    )
"""
    migration_files = {"posthog/migrations/1117_alter_integration_kind.py": migration_content}
    base_files = {"posthog/models/integration.py": base_model_content}

    assert detect_noop_migration_files(migration_files, base_files) == {
        "posthog/migrations/1117_alter_integration_kind.py"
    }


def test_changed_db_field_attribute_is_not_noop_migration() -> None:
    migration_content = """
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.AlterField(
            model_name="integration",
            name="kind",
            field=models.CharField(
                choices=[
                    ("slack", "Slack"),
                    ("postgresql", "Postgresql"),
                ],
                max_length=64,
            ),
        ),
    ]
"""
    base_model_content = """
from django.db import models


class Integration(models.Model):
    kind = models.CharField(max_length=32, choices=[("slack", "Slack")])
"""
    migration_files = {"posthog/migrations/1117_alter_integration_kind.py": migration_content}
    base_files = {"posthog/models/integration.py": base_model_content}

    assert detect_noop_migration_files(migration_files, base_files) == set()


def test_noop_migration_and_max_migration_can_be_ignored_for_deny_list() -> None:
    noop_files = {"posthog/migrations/1117_alter_integration_kind.py"}
    ignored_files = noop_files | migration_bookkeeping_files_for(noop_files)
    files = [
        "posthog/migrations/1117_alter_integration_kind.py",
        "posthog/migrations/max_migration.txt",
    ]

    assert detect_deny_categories(files, "feat: add postgresql integration", ignored_files=ignored_files) == []


@pytest.mark.parametrize(
    "migration_path, migration_content, subject",
    [
        pytest.param(
            "posthog/migrations/1117_integration_new_field.py",
            """
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.AddField(
            model_name="integration",
            name="new_field",
            field=models.CharField(max_length=32, null=True),
        ),
    ]
""",
            "feat: add integration field",
            id="add-field",
        ),
        pytest.param(
            "posthog/migrations/1117_create_team_preferences.py",
            """
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.CreateModel(
            name="TeamPreferences",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("theme", models.CharField(max_length=16)),
            ],
        ),
    ]
""",
            "feat: add team preferences model",
            id="create-model",
        ),
        pytest.param(
            "posthog/migrations/1117_remove_integration_legacy_flag.py",
            """
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.RemoveField(
            model_name="integration",
            name="legacy_flag",
        ),
    ]
""",
            "chore: drop integration.legacy_flag",
            id="remove-field",
        ),
        pytest.param(
            "posthog/migrations/1117_rename_integration_kind_column.py",
            """
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.RenameField(
            model_name="integration",
            old_name="kind",
            new_name="kind_type",
        ),
    ]
""",
            "refactor: rename integration.kind to kind_type",
            id="rename-field",
        ),
        pytest.param(
            "posthog/migrations/1117_add_integration_team_kind_index.py",
            """
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.AddIndex(
            model_name="integration",
            index=models.Index(fields=["team_id", "kind"], name="integration_team_kind_idx"),
        ),
    ]
""",
            "perf: add index on integration(team_id, kind)",
            id="add-index",
        ),
        pytest.param(
            "posthog/migrations/1117_add_integration_kind_unique.py",
            """
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.AddConstraint(
            model_name="integration",
            constraint=models.UniqueConstraint(fields=["team_id", "kind"], name="uniq_integration_team_kind"),
        ),
    ]
""",
            "feat: enforce unique (team, kind) on integration",
            id="add-constraint",
        ),
        pytest.param(
            "posthog/migrations/1117_backfill_integration_kind.py",
            """
from django.db import migrations


def forwards(apps, schema_editor):
    Integration = apps.get_model("posthog", "Integration")
    Integration.objects.filter(kind="slack_v1").update(kind="slack")


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
""",
            "chore: backfill integration.kind values",
            id="run-python-backfill",
        ),
        pytest.param(
            "posthog/migrations/1117_drop_legacy_view.py",
            """
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_previous")]

    operations = [
        migrations.RunSQL(
            sql="DROP VIEW IF EXISTS legacy_integration_summary;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
""",
            "chore: drop legacy_integration_summary view",
            id="run-sql",
        ),
    ],
)
def test_real_migration_still_matches_deny_list(migration_path: str, migration_content: str, subject: str) -> None:
    migration_files = {migration_path: migration_content}

    assert detect_noop_migration_files(migration_files, {}) == set()
    assert detect_deny_categories(list(migration_files), subject) == ["migrations"]


def test_mixed_noop_and_real_migration_still_matches_deny_list() -> None:
    noop_files = {"posthog/migrations/1117_alter_integration_kind.py"}
    ignored_files = noop_files | migration_bookkeeping_files_for(noop_files)
    files = [
        "posthog/migrations/1117_alter_integration_kind.py",
        "posthog/migrations/1118_add_column.py",
        "posthog/migrations/max_migration.txt",
    ]

    assert detect_deny_categories(files, "feat: add integration field", ignored_files=ignored_files) == ["migrations"]
