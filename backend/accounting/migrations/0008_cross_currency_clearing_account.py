from django.db import migrations

class Migration(migrations.Migration):
    """Schema checkpoint for the Phase 10B clearing-account contract.

    The canonical COA is data-seeded by accounting.coa.seed_chart_of_accounts;
    migrations must not assume canonical COA rows already exist.
    """
    dependencies = [("accounting", "0007_fx_settlement_record")]
    operations = []
