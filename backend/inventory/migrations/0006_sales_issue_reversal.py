from django.db import migrations, models


IN_TYPES = [
    "ADJUSTMENT_IN", "OPENING", "PURCHASE_RECEIPT", "SALES_RETURN",
    "SALES_ISSUE_REVERSAL", "TRANSFER_IN",
]
OUT_TYPES = [
    "ADJUSTMENT_OUT", "PURCHASE_RETURN", "SALES_ISSUE", "TRANSFER_OUT",
]


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_stockmovement_source_party"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockmovement",
            name="movement_type",
            field=models.CharField(
                choices=[
                    ("PURCHASE_RECEIPT", "Purchase Receipt"),
                    ("SALES_ISSUE", "Sales Issue"),
                    ("SALES_ISSUE_REVERSAL", "Sales Issue Reversal"),
                    ("SALES_RETURN", "Sales Return"),
                    ("PURCHASE_RETURN", "Purchase Return"),
                    ("TRANSFER_IN", "Transfer In"),
                    ("TRANSFER_OUT", "Transfer Out"),
                    ("ADJUSTMENT_IN", "Adjustment In"),
                    ("ADJUSTMENT_OUT", "Adjustment Out"),
                    ("SHORTAGE", "Shortage"),
                    ("OPENING", "Opening"),
                ],
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="stockmovement",
            name="inv_movement_direction",
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(movement_type__in=IN_TYPES, quantity__gt=0)
                    | models.Q(movement_type__in=OUT_TYPES, quantity__lt=0)
                ),
                name="inv_movement_direction",
            ),
        ),
    ]
