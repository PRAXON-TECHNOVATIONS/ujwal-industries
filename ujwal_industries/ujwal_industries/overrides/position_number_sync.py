import frappe


POSITION_FIELDNAME = "custom_po_no"


def _set_position_numbers(doc, *, overwrite: bool = True):
	for index, item in enumerate(doc.get("items", []), start=1):
		if not overwrite and item.get(POSITION_FIELDNAME):
			continue
		item.set(POSITION_FIELDNAME, str(index * 10))


def _sync_linked_row(doctype, row_name, position_number):
	if not row_name:
		return

	frappe.db.set_value(doctype, row_name, POSITION_FIELDNAME, position_number, update_modified=False)


def _sync_rows_by_filters(doctype, filters, position_number):
	if not filters:
		return

	row_names = frappe.get_all(doctype, filters=filters, pluck="name")
	for row_name in row_names:
		_sync_linked_row(doctype, row_name, position_number)


def _sync_sales_order_row(item):
	_sync_linked_row("Sales Order Item", item.get("so_detail"), item.get(POSITION_FIELDNAME))


def _sync_delivery_note_row(item):
	_sync_linked_row("Delivery Note Item", item.get("dn_detail"), item.get(POSITION_FIELDNAME))


def sync_sales_order_position_numbers(doc, method=None):
	# Auto-numbering disabled: Pos. NO. (custom_po_no) is now manually editable
	# on Sales Order so users can insert/renumber rows (e.g. 10, 20, 40).
	# To revert to auto sequential numbering (10, 20, 30, ...), uncomment the
	# line below and set custom_po_no's read_only back to 1 on Sales Order Item.
	# _set_position_numbers(doc)

	for item in doc.get("items", []):
		position_number = item.get(POSITION_FIELDNAME)
		_sync_rows_by_filters("Delivery Note Item", {"so_detail": item.name}, position_number)
		_sync_rows_by_filters("Sales Invoice Item", {"so_detail": item.name}, position_number)


def sync_delivery_note_position_numbers(doc, method=None):
	_set_position_numbers(doc, overwrite=False)

	for item in doc.get("items", []):
		_sync_sales_order_row(item)
		_sync_rows_by_filters("Sales Invoice Item", {"dn_detail": item.name}, item.get(POSITION_FIELDNAME))


def sync_sales_invoice_position_numbers(doc, method=None):
	_set_position_numbers(doc, overwrite=False)

	for item in doc.get("items", []):
		_sync_sales_order_row(item)
		_sync_delivery_note_row(item)
