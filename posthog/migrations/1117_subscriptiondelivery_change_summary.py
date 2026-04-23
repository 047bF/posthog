from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1116_datadeletionrequest_hogql_predicate")]

    operations = [
        migrations.AddField(
            model_name="subscriptiondelivery",
            name="change_summary",
            field=models.TextField(blank=True, null=True),
        ),
    ]
