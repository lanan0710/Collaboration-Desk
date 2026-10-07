from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("demands", "0002_alter_submission_result_url_submissionattachment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="submission",
            name="result_url",
            field=models.URLField(max_length=1000, verbose_name="成果链接"),
        ),
    ]
