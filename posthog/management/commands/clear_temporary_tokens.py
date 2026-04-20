from django.core.management.base import BaseCommand
from django.db import connection

from posthog.models import User

BATCH_SIZE = 5000


class Command(BaseCommand):
    help = "Clear temporary_token for all users (one-time cleanup after migrating to toolbar OAuth)"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Rows per UPDATE batch")

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        total_updated = 0
        user_table = connection.ops.quote_name(User._meta.db_table)

        # `temporary_token` is a deprecated field (django-deprecate-fields) and is not exposed on the ORM.
        while True:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {user_table} AS u
                    SET temporary_token = NULL
                    FROM (
                        SELECT id FROM {user_table}
                        WHERE temporary_token IS NOT NULL AND temporary_token <> ''
                        LIMIT %s
                    ) AS batch
                    WHERE u.id = batch.id
                    """,
                    [batch_size],
                )
                updated = cursor.rowcount
            if not updated:
                break
            total_updated += updated
            self.stdout.write(f"  Cleared {updated} rows (total so far: {total_updated})")

        if total_updated == 0:
            self.stdout.write("No users with temporary tokens found.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Cleared temporary_token for {total_updated} user(s)."))
