import frappe

def validate_processing_time_before_submit(doc, method):
    """
    Ensure Actual Processing Time is entered for all items
    before submitting Purchase Receipt.
    """

    for row in doc.items:
        if not row.custom_actual_processing_days or row.custom_actual_processing_days <= 0:
            frappe.throw(
                ("Row {0}: Please enter Actual Processing Time (Days) before submitting.")
                .format(row.idx),
                title=("Missing Processing Time")
            )
