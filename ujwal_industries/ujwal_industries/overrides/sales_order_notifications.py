import frappe
from frappe.desk.form import assign_to
from frappe.utils.user import get_users_with_role


def _assign(args: dict):
	"""
	Create the assignment without checking the current user's permission on the document.
	Frappe moved that option: up to ~v15.79 it is assign_to.add(args, ignore_permissions=True);
	in later v15 (e.g. 15.122) add() no longer accepts it and the private _add() takes it.
	Works on both, so a Frappe update can't break WO / MR / PO creation again.
	"""
	if hasattr(assign_to, "_add"):
		return assign_to._add(args, ignore_permissions=True)
	return assign_to.add(args, ignore_permissions=True)


def notify_planning_supervisor_on_submit(doc, method):
	recipients = get_users_with_role("Planning supervisor")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": f"Sales Order {doc.name} submitted for {doc.customer_name or doc.customer}. Please review and begin planning.",
			}
		)


def notify_production_supervisor_on_work_order_create(doc, method):
	recipients = get_users_with_role("Production manager")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": (
					f"Work Order {doc.name} for item {doc.production_item} has been created from Production Plan. "
					"Please review and proceed with the production execution."
				),
			}
		)


def notify_outsource_store_manager_on_subcontract_create(doc, method):
	recipients = get_users_with_role("Outsource Store Manager")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": (
					f"Subcontracting Order {doc.name} for item {(doc.items[0].item_name if doc.items else None) or doc.name} has been created from Production Plan. "
					"Please coordinate with the vendor and ensure materials are dispatched accordingly."
				),
			}
		)


def notify_store_incharge_on_material_request_create(doc, method):
	recipients = get_users_with_role("Store Incharge")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": (
					f"Material Request {doc.name} has been created from Production Plan. "
					"Please review the requested materials and process the necessary stock arrangements."
				),
			}
		)


def notify_sales_purchase_head_on_material_request_submit(doc, method):
	recipients = get_users_with_role("Sales and Purchase Head")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": (
					f"Material Request {doc.name} has been submitted. "
					"Please review and take the necessary procurement or fulfillment action."
				),
			}
		)


def notify_store_incharge_on_purchase_order_submit(doc, method):
	recipients = get_users_with_role("Store Incharge")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": (
					f"Purchase Order {doc.name} for supplier {doc.supplier_name or doc.supplier} has been submitted. "
					"Upon receiving the goods, please create a Purchase Receipt to record the incoming stock and update inventory accordingly."
				),
			}
		)


def notify_store_incharge_on_work_order_submit(doc, method):
	recipients = get_users_with_role("Store Incharge")
	if not recipients:
		return

	for user in recipients:
		_assign(
			{
				"assign_to": [user],
				"doctype": doc.doctype,
				"name": doc.name,
				"description": (
					f"Work Order {doc.name} for item {doc.production_item} has been submitted. "
					"Please initiate the required stock movements via Stock Entry to ensure "
					"raw materials are transferred to the shop floor before production begins."
				),
			}
		)
