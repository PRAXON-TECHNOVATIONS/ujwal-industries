import frappe
from frappe.utils import now_datetime, time_diff_in_seconds

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

def set_actual_processing_time(doc, method):
    if not doc.custom_gate_pass:
        return
    
    gate_pass = frappe.get_doc("Gate Pass", doc.custom_gate_pass)
    gp_created_time = gate_pass.creation
    
    if doc.docstatus == 1:
        pr_created_time = doc.creation
    
    total_seconds = time_diff_in_seconds(pr_created_time, gp_created_time)
    total_minutes = int(total_seconds // 60) 
    days = total_minutes // (24 * 60)
    minutes = total_minutes % (24 * 60)
    result = f"{days}.{minutes:02d}"
    for row in doc.items:
        row.db_set("custom_actual_processing_days", result)
        frappe.db.commit()
        


def before_insert(doc, method):
    if doc.amended_from:
        if frappe.db.exists("Sales Receipt", doc.amended_from):
            frappe.delete_doc("Sales Receipt", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None        