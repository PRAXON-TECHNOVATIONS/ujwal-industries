import frappe
from frappe.desk.form import assign_to
from frappe.utils.user import get_users_with_role


def notify_planning_supervisor_on_submit(doc, method):
	recipients = get_users_with_role("Planning supervisor")
	if not recipients:
		return

	for user in recipients:
		assign_to.add(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": f"Sales Order {doc.name} submitted for {doc.customer_name or doc.customer}. Please review and begin planning.",
			},
			ignore_permissions=True,
		)
