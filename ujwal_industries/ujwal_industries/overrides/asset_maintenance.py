import frappe
from frappe.utils import add_days


def set_end_date_from_asset(doc, method=None):
    """
    On save:
    If start_date exists, fetch maintenance days from Asset
    and auto-set end_date
    """

    if not doc.asset_name:
        return

    # Fetch required maintenance days from Asset
    required_days = frappe.db.get_value(
        "Asset",
        doc.asset_name,
        "custom_required_maintenance_days"
    ) or 0

    if not required_days:
        return

    for row in doc.asset_maintenance_tasks or []:

        if not row.start_date:
            continue

        # Always force-calculate (as per your requirement)
        row.end_date = add_days(row.start_date, required_days)

def validate_periodicity(doc, method=None):

    for row in doc.asset_maintenance_tasks or []:

        # Workstation → Periodicity required
        if doc.asset_category == "Workstation" and not row.periodicity:
            frappe.throw(
                f"Row #{row.idx}: Periodicity is mandatory for Workstation assets"
            )

        # Tools → force empty
        if doc.asset_category == "Tools":
            row.periodicity = None
