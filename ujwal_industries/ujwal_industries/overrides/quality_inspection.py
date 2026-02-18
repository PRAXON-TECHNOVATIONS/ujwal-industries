import frappe
from frappe.utils import getdate, date_diff, flt

def update_grn_processing_time(doc, method=None):
    """
    Calculate actual GRN processing days (DATE based)
    when Quality Inspection is submitted
    """

    # Only for Purchase Receipt
    if doc.reference_type != "Purchase Receipt":
        return

    if not doc.reference_name or not doc.item_code:
        return

    # Fetch Purchase Receipt
    try:
        pr = frappe.get_doc("Purchase Receipt", doc.reference_name)
    except frappe.DoesNotExistError:
        return

    # START DATE → PR posting date
    pr_posting_date = getdate(pr.posting_date)

    # END DATE → QI submission date
    qi_submit_date = getdate(doc.modified)

    # Safety check
    if qi_submit_date < pr_posting_date:
        return

    # Date difference in days
    actual_days = flt(date_diff(qi_submit_date, pr_posting_date))

    # Update matching PR item row
    for item in pr.items:
        if item.item_code == doc.item_code:
            item.custom_actual_processing_days = actual_days
            break

    # Save silently
    pr.db_set("modified", pr.modified)
    pr.save(ignore_permissions=True)
