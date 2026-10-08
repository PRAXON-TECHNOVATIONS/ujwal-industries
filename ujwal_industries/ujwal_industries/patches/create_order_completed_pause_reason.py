# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe


def execute():
    """Create the 'Order Completed' Job Card Pause Reason used to mark a
    Job Card as Completed pre-submit (see job_card.apply_order_completed_status)."""

    if not frappe.db.exists("Job Card Pause Reason", "Order Completed"):
        doc = frappe.new_doc("Job Card Pause Reason")
        doc.name1 = "Order Completed"
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
