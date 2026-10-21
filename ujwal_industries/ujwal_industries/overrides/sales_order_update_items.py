import json
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext.controllers.accounts_controller import update_child_qty_rate as erpnext_update_child_qty_rate
from erpnext.controllers.accounts_controller import validate_child_on_delete
from erpnext.stock.get_item_details import get_conversion_factor, get_item_tax_map, get_item_tax_template


ORDER_CONFIG = {
	"Sales Order": {
		"child_doctype": "Sales Order Item",
		"date_field": "delivery_date",
		"invoice_item_doctype": "Sales Invoice Item",
		"invoice_link_field": "so_detail",
	},
	"Purchase Order": {
		"child_doctype": "Purchase Order Item",
		"date_field": "schedule_date",
		"invoice_item_doctype": "Purchase Invoice Item",
		"invoice_link_field": "po_detail",
	},
}

# Only this role (and Administrator) can approve / reject item update requests.
APPROVER_ROLE = "Super Approver"

# Orders in these statuses are frozen on purpose -- no item updates at all.
LOCKED_STATUSES = ("Closed", "On Hold")

APPROVAL_STATUS_FIELD = "custom_update_approval_status"
APPROVAL_REASON_FIELD = "custom_update_request_reason"
APPROVAL_DATA_FIELD = "custom_update_request_data"
PENDING_APPROVAL_STATUS = "Pending Approval"
APPROVED_STATUS = "Approved"

# Stored in the row's request data. A row removed in the Update Items dialog
# is not deleted right away -- it stays (greyed out) as a pending delete
# request and is only deleted once the Super Approver approves it.
ACTION_DELETE = "delete"

POSITION_FIELDNAME = "custom_po_no"

# Once any of these is non-zero on a row, other documents reference that row's
# item, so the item can no longer be swapped.
ITEM_SWAP_BLOCKING_FIELDS = {
	"Sales Order": {
		"delivered_qty": "Delivered Qty",
		"billed_amt": "Billed Amount",
		"returned_qty": "Returned Qty",
		"production_plan_qty": "Production Plan Qty",
		"work_order_qty": "Work Order Qty",
		"ordered_qty": "Ordered Qty",
	},
	"Purchase Order": {
		"received_qty": "Received Qty",
		"billed_amt": "Billed Amount",
		"returned_qty": "Returned Qty",
	},
}

# Same idea for deleting a row -- plus reserved stock on Sales Order rows.
ROW_DELETE_BLOCKING_FIELDS = {
	"Sales Order": {**ITEM_SWAP_BLOCKING_FIELDS["Sales Order"], "stock_reserved_qty": "Stock Reserved Qty"},
	"Purchase Order": ITEM_SWAP_BLOCKING_FIELDS["Purchase Order"],
}


@frappe.whitelist()
def update_child_qty_rate(parent_doctype, trans_items, parent_doctype_name, child_docname="items", reason=None):
	if parent_doctype not in ORDER_CONFIG:
		return erpnext_update_child_qty_rate(
			parent_doctype=parent_doctype,
			trans_items=trans_items,
			parent_doctype_name=parent_doctype_name,
			child_docname=child_docname,
		)

	doc = frappe.get_doc(parent_doctype, parent_doctype_name)
	incoming_items = _parse_trans_items(trans_items)

	_validate_order_editable(doc)
	_ensure_no_pending_item_approvals(doc, child_docname)

	deleted_rows = _get_requested_deletions(doc, child_docname, incoming_items)
	_validate_row_deletions(doc, deleted_rows, incoming_items)

	if parent_doctype == "Sales Order":
		_validate_sales_order_update_items_qty_lock(parent_doctype_name, incoming_items)
		_validate_position_numbers_present(incoming_items)

	_validate_qty_not_below_billed(doc, child_docname, incoming_items)
	_validate_row_dates(doc, incoming_items)

	# Rows removed in the dialog go back into the payload unchanged so core
	# doesn't delete them now; they are marked as pending delete instead.
	incoming_items.extend(_build_row_payload(row, parent_doctype) for row in deleted_rows)

	before_rows = _get_row_snapshots(doc, child_docname, parent_doctype)

	# Core update_child_qty_rate never changes item_code on an existing row,
	# so apply item swaps ourselves; the swapped rows then flow through the
	# normal change detection -> Pending Approval path below.
	item_code_changes = _get_item_code_changes(doc, child_docname, incoming_items)
	if item_code_changes:
		_validate_item_code_changes(doc, item_code_changes, validate_new_item=True)
		_apply_item_code_changes(doc, item_code_changes)

	trans_items = frappe.as_json(incoming_items)

	if parent_doctype == "Sales Order":
		with _position_number_not_mandatory():
			result = erpnext_update_child_qty_rate(
				parent_doctype=parent_doctype,
				trans_items=trans_items,
				parent_doctype_name=parent_doctype_name,
				child_docname=child_docname,
			)
	else:
		result = erpnext_update_child_qty_rate(
			parent_doctype=parent_doctype,
			trans_items=trans_items,
			parent_doctype_name=parent_doctype_name,
			child_docname=child_docname,
		)

	if item_code_changes:
		_refresh_bins_for_replaced_items(parent_doctype, item_code_changes)

	updated_doc = frappe.get_doc(parent_doctype, parent_doctype_name)

	if parent_doctype == "Sales Order":
		_apply_position_numbers(updated_doc, child_docname, before_rows, incoming_items)

	changed_rows = _get_changed_rows(before_rows, updated_doc, child_docname, parent_doctype)
	changed_rows.extend(_build_delete_requests(before_rows, deleted_rows))

	if changed_rows:
		_mark_rows_pending_approval(updated_doc, changed_rows, parent_doctype, reason)
		_log_reason(parent_doctype, parent_doctype_name, reason)
		_log_item_update_request(parent_doctype, parent_doctype_name, updated_doc, changed_rows, reason)
		_notify_approvers(parent_doctype, parent_doctype_name, updated_doc, changed_rows, reason)

	return result


@frappe.whitelist()
def approve_pending_item_updates(doctype, docname):
	if doctype not in ORDER_CONFIG:
		frappe.throw(_("Approval is only supported for Sales Order and Purchase Order item updates."))

	_ensure_approval_permission()

	doc = frappe.get_doc(doctype, docname)
	pending_rows = _get_pending_rows(doc)

	if not pending_rows:
		frappe.msgprint(_("There are no pending item updates to approve."))
		return

	# Capture everything needed for the log / notification before the
	# approved delete rows disappear.
	row_details = _describe_pending_rows(doctype, pending_rows)
	requesters = _get_requesters(pending_rows)

	delete_rows = [row for row in pending_rows if _is_delete_request(row)]
	if delete_rows:
		_delete_approved_rows(doc, delete_rows)

	delete_names = {row.name for row in delete_rows}
	_set_row_approval_status(doctype, [row for row in pending_rows if row.name not in delete_names], APPROVED_STATUS)

	_log_item_update_approval(doctype, docname, row_details)
	_notify_requesters(doctype, docname, requesters, approved=True, row_details=row_details)

	frappe.msgprint(_("Pending item updates approved successfully."))


@frappe.whitelist()
def reject_pending_item_updates(doctype, docname, reason=None):
	if doctype not in ORDER_CONFIG:
		frappe.throw(_("Approval is only supported for Sales Order and Purchase Order item updates."))

	_ensure_approval_permission()

	doc = frappe.get_doc(doctype, docname)
	pending_rows = _get_pending_rows(doc)

	if not pending_rows:
		frappe.msgprint(_("There are no pending item updates to reject."))
		return

	row_details = _describe_pending_rows(doctype, pending_rows)
	requesters = _get_requesters(pending_rows)

	reverted_items = _build_reverted_items_payload(doc, doctype, pending_rows)

	item_code_changes = _get_item_code_changes(doc, "items", reverted_items)
	if item_code_changes:
		_validate_item_code_changes(doc, item_code_changes, validate_new_item=False)
		_apply_item_code_changes(doc, item_code_changes)

	frappe.flags.ujwal_skip_item_update_approval = True
	try:
		erpnext_update_child_qty_rate(
			parent_doctype=doctype,
			trans_items=frappe.as_json(reverted_items),
			parent_doctype_name=docname,
			child_docname="items",
		)
	finally:
		frappe.flags.ujwal_skip_item_update_approval = False

	if item_code_changes:
		_refresh_bins_for_replaced_items(doctype, item_code_changes)

	reverted_doc = frappe.get_doc(doctype, docname)
	reverted_names = {row.name for row in reverted_doc.get("items", [])}
	remaining_pending_rows = [row for row in pending_rows if row.name in reverted_names]
	_clear_row_approval_state(doctype, remaining_pending_rows)
	_log_item_update_rejection(doctype, docname, pending_rows, reason)
	_notify_requesters(doctype, docname, requesters, approved=False, row_details=row_details, reason=reason)

	frappe.msgprint(_("Pending item updates rejected and reverted successfully."))


def _ensure_approval_permission():
	if frappe.session.user == "Administrator":
		return

	if APPROVER_ROLE not in frappe.get_roles():
		frappe.throw(_("Only users with the {0} role can approve or reject item updates.").format(APPROVER_ROLE))


def _validate_order_editable(doc):
	if doc.docstatus != 1:
		frappe.throw(_("Update Items is only available on a submitted {0}.").format(doc.doctype))

	if doc.status in LOCKED_STATUSES:
		frappe.throw(_("Items cannot be updated while {0} {1} is {2}.").format(doc.doctype, doc.name, doc.status))

	if doc.doctype == "Purchase Order" and not doc.can_update_items():
		frappe.throw(_("Items cannot be updated because a Subcontracting Order exists against this Purchase Order."))


def _get_requested_deletions(doc, child_docname, incoming_items):
	incoming_docnames = {row.get("docname") for row in incoming_items if row.get("docname")}
	return [row for row in doc.get(child_docname, []) if row.name not in incoming_docnames]


def _validate_row_deletions(doc, deleted_rows, incoming_items):
	if not deleted_rows:
		return

	if not any(row.get("item_code") for row in incoming_items):
		frappe.throw(_("At least one item must remain on the {0}.").format(doc.doctype))

	errors = []
	for row in deleted_rows:
		blocking = [
			_(label)
			for fieldname, label in ROW_DELETE_BLOCKING_FIELDS[doc.doctype].items()
			if flt(row.get(fieldname)) > 0
		]
		if blocking:
			errors.append(
				_("Row #{0} ({1}) cannot be deleted because it is already linked ({2}).").format(
					row.idx, row.item_code, ", ".join(blocking)
				)
			)

	if errors:
		frappe.throw("<br>".join(errors))

	# Core's own delete checks, so the request fails now rather than at approval.
	for row in deleted_rows:
		validate_child_on_delete(row, doc)


def _build_row_payload(row, parent_doctype):
	payload = _build_row_snapshot(row, parent_doctype)
	payload["docname"] = row.name
	if parent_doctype == "Sales Order":
		payload[POSITION_FIELDNAME] = row.get(POSITION_FIELDNAME)
	return payload


def _build_delete_requests(before_rows, deleted_rows):
	return [
		{
			"row_name": row.name,
			"action": ACTION_DELETE,
			"old_values": before_rows.get(row.name) or {},
			"new_values": {},
			"changed_fields": [],
		}
		for row in deleted_rows
	]


def _is_delete_request(row):
	return _get_row_request_data(row).get("action") == ACTION_DELETE


def _delete_approved_rows(doc, delete_rows):
	"""Re-check the rows (something may have been made against them since the
	request) and let core delete them, which also fixes bins / prevdoc status."""

	delete_names = {row.name for row in delete_rows}
	remaining_items = [_build_row_payload(row, doc.doctype) for row in doc.get("items", []) if row.name not in delete_names]
	_validate_row_deletions(doc, delete_rows, remaining_items)

	frappe.flags.ujwal_skip_item_update_approval = True
	try:
		erpnext_update_child_qty_rate(
			parent_doctype=doc.doctype,
			trans_items=frappe.as_json(remaining_items),
			parent_doctype_name=doc.name,
			child_docname="items",
		)
	finally:
		frappe.flags.ujwal_skip_item_update_approval = False


def _validate_qty_not_below_billed(doc, child_docname, incoming_items):
	"""Core only stops qty going below delivered / received qty -- also stop it
	going below what is already invoiced (SI / PI, net of returns)."""

	rows_by_name = {row.name: row for row in doc.get(child_docname, [])}
	row_names = [row.get("docname") for row in incoming_items if row.get("docname") in rows_by_name]
	if not row_names:
		return

	config = ORDER_CONFIG[doc.doctype]
	billed = frappe.db.sql(
		f"""
		SELECT `{config["invoice_link_field"]}` AS row_name, SUM(stock_qty) AS stock_qty
		FROM `tab{config["invoice_item_doctype"]}`
		WHERE docstatus = 1 AND `{config["invoice_link_field"]}` IN %(row_names)s
		GROUP BY `{config["invoice_link_field"]}`
		""",
		{"row_names": row_names},
		as_dict=True,
	)
	billed_by_row = {row.row_name: flt(row.stock_qty) for row in billed}

	errors = []
	for incoming in incoming_items:
		row = rows_by_name.get(incoming.get("docname"))
		billed_stock_qty = billed_by_row.get(incoming.get("docname"))
		if not row or not billed_stock_qty:
			continue

		conversion_factor = flt(incoming.get("conversion_factor")) or flt(row.conversion_factor) or 1
		if flt(incoming.get("qty")) * conversion_factor < billed_stock_qty - 0.0001:
			errors.append(
				_("Row #{0} ({1}): Qty cannot be less than the already invoiced qty {2}.").format(
					row.idx, row.item_code, frappe.format_value(billed_stock_qty / conversion_factor, {"fieldtype": "Float"})
				)
			)

	if errors:
		frappe.throw("<br>".join(errors))


def _validate_row_dates(doc, incoming_items):
	date_field = ORDER_CONFIG[doc.doctype]["date_field"]
	label = _("Delivery Date") if doc.doctype == "Sales Order" else _("Reqd By Date")
	order_date = getdate(doc.transaction_date)

	errors = [
		_("{0} {1} for item {2} cannot be before the order date {3}.").format(
			label,
			frappe.format_value(row.get(date_field), {"fieldtype": "Date"}),
			row.get("item_code"),
			frappe.format_value(doc.transaction_date, {"fieldtype": "Date"}),
		)
		for row in incoming_items
		if row.get("item_code") and row.get(date_field) and getdate(row.get(date_field)) < order_date
	]
	if errors:
		frappe.throw("<br>".join(errors))


def _ensure_no_pending_item_approvals(doc, child_docname):
	pending_rows = [row.idx for row in doc.get(child_docname, []) if row.get(APPROVAL_STATUS_FIELD) == PENDING_APPROVAL_STATUS]
	if pending_rows:
		row_list = ", ".join(str(idx) for idx in pending_rows)
		frappe.throw(
			_("Row(s) {0} are already pending approval. Approve them before making another item update.").format(row_list)
		)


def _get_pending_rows(doc, child_docname="items"):
	return [row for row in doc.get(child_docname, []) if row.get(APPROVAL_STATUS_FIELD) == PENDING_APPROVAL_STATUS]


def _get_item_code_changes(doc, child_docname, incoming_items):
	rows_by_name = {row.name: row for row in doc.get(child_docname, [])}
	changes = []
	for incoming in incoming_items:
		row = rows_by_name.get(incoming.get("docname"))
		new_item_code = incoming.get("item_code")
		if row and new_item_code and new_item_code != row.item_code:
			changes.append(
				frappe._dict(
					row=row,
					incoming=incoming,
					old_item_code=row.item_code,
					new_item_code=new_item_code,
				)
			)
	return changes


def _validate_item_code_changes(doc, changes, validate_new_item):
	errors = []

	if doc.doctype == "Purchase Order" and doc.get("is_subcontracted"):
		frappe.throw(_("Item Code cannot be changed on a subcontracted Purchase Order."))

	for change in changes:
		row = change.row
		row_label = _("Row #{0} ({1} -> {2})").format(row.idx, change.old_item_code, change.new_item_code)

		blocking = [
			_(label)
			for fieldname, label in ITEM_SWAP_BLOCKING_FIELDS[doc.doctype].items()
			if flt(row.get(fieldname)) > 0
		]
		if row.get("blanket_order"):
			blocking.append(_("Blanket Order"))
		if doc.doctype == "Purchase Order":
			if row.get("material_request_item"):
				blocking.append(_("Material Request"))
			if row.get("sales_order_item"):
				blocking.append(_("Sales Order"))

		if blocking:
			errors.append(
				_("{0}: Item Code cannot be changed because the row is already linked ({1}).").format(
					row_label, ", ".join(blocking)
				)
			)
			continue

		if not validate_new_item:
			continue

		item = frappe.db.get_value(
			"Item",
			change.new_item_code,
			["disabled", "has_variants", "is_sales_item", "is_purchase_item"],
			as_dict=True,
		)
		if not item:
			errors.append(_("{0}: Item {1} does not exist.").format(row_label, change.new_item_code))
		elif item.disabled:
			errors.append(_("{0}: Item {1} is disabled.").format(row_label, change.new_item_code))
		elif item.has_variants:
			errors.append(_("{0}: Item {1} is a template, select a variant.").format(row_label, change.new_item_code))
		elif doc.doctype == "Sales Order" and not item.is_sales_item:
			errors.append(_("{0}: Item {1} is not a sales item.").format(row_label, change.new_item_code))
		elif doc.doctype == "Purchase Order" and not item.is_purchase_item:
			errors.append(_("{0}: Item {1} is not a purchase item.").format(row_label, change.new_item_code))

	if errors:
		frappe.throw("<br>".join(errors))


def _apply_item_code_changes(doc, changes):
	"""Swap the item on existing rows and refresh everything that is derived
	from the item (name, description, HSN, UOM, tax template, BOM, ...).
	The incoming payload's uom / conversion_factor are aligned with what is
	written here, so core update_child_qty_rate doesn't revert them."""

	child_doctype = ORDER_CONFIG[doc.doctype]["child_doctype"]
	meta = frappe.get_meta(child_doctype)

	for change in changes:
		row = change.row
		item = frappe.get_cached_doc("Item", change.new_item_code)

		values = {
			"item_code": item.name,
			"item_name": item.item_name,
			"description": item.description or item.item_name,
			"item_group": item.item_group,
			"brand": item.brand,
			"stock_uom": item.stock_uom,
			"weight_per_unit": item.weight_per_unit,
			"weight_uom": item.weight_uom,
		}

		# fetch_from fields: gst_hsn_code, image, and any custom item_code.* fetches
		for df in meta.fields:
			if df.fetch_from and df.fetch_from.startswith("item_code."):
				values[df.fieldname] = item.get(df.fetch_from.split(".", 1)[1])

		uom = change.incoming.get("uom") or row.uom
		if uom != item.stock_uom and not any(d.uom == uom for d in item.get("uoms", [])):
			uom = item.stock_uom
		conversion_factor = flt(get_conversion_factor(item.name, uom).get("conversion_factor")) or 1
		values.update({"uom": uom, "conversion_factor": conversion_factor})
		change.incoming.update({"uom": uom, "conversion_factor": conversion_factor})

		item_tax_template = get_item_tax_template(
			{
				"company": doc.company,
				"tax_category": doc.get("tax_category"),
				"transaction_date": doc.transaction_date,
				"base_net_rate": row.base_net_rate,
				"item_tax_template": row.item_tax_template,
			},
			item,
		)
		values["item_tax_template"] = item_tax_template
		values["item_tax_rate"] = get_item_tax_map(doc.company, item_tax_template)

		if doc.doctype == "Sales Order":
			values["bom_no"] = item.default_bom
			change.incoming.pop("bom_no", None)

		values = {fieldname: value for fieldname, value in values.items() if meta.has_field(fieldname)}
		frappe.db.set_value(child_doctype, row.name, values, update_modified=False)


def _refresh_bins_for_replaced_items(doctype, changes):
	"""Core update_child_qty_rate refreshes reserved / ordered qty only for the
	items currently on the order, so recompute it for the replaced items."""

	from erpnext.stock.stock_balance import get_ordered_qty, get_reserved_qty, update_bin_qty

	for change in changes:
		warehouse = change.row.warehouse
		if not warehouse or not frappe.get_cached_value("Item", change.old_item_code, "is_stock_item"):
			continue

		if doctype == "Sales Order":
			qty_dict = {"reserved_qty": get_reserved_qty(change.old_item_code, warehouse)}
		else:
			qty_dict = {"ordered_qty": get_ordered_qty(change.old_item_code, warehouse)}

		update_bin_qty(change.old_item_code, warehouse, qty_dict)


def _parse_trans_items(trans_items):
	if isinstance(trans_items, str):
		return json.loads(trans_items)

	return trans_items or []


def _get_row_snapshots(doc, child_docname, parent_doctype):
	snapshots = {}
	for row in doc.get(child_docname, []):
		snapshots[row.name] = _build_row_snapshot(row, parent_doctype)
	return snapshots


def _build_row_snapshot(row, parent_doctype):
	config = ORDER_CONFIG[parent_doctype]
	fields = [
		"item_code",
		"qty",
		"rate",
		"uom",
		"conversion_factor",
		config["date_field"],
	]

	if parent_doctype == "Purchase Order":
		fields.extend(["fg_item", "fg_item_qty"])

	snapshot = {}
	for fieldname in fields:
		snapshot[fieldname] = row.get(fieldname)
	return snapshot


def _validate_position_numbers_present(incoming_items):
	missing_rows = [
		row.get("item_code") or _("(new row)")
		for row in incoming_items
		if row.get("item_code") and not row.get(POSITION_FIELDNAME)
	]
	if missing_rows:
		frappe.throw(
			_("Pos. NO. is mandatory for every item row: {0}").format(", ".join(missing_rows))
		)


@contextmanager
def _position_number_not_mandatory():
	"""Sales Order Item's custom_po_no is a mandatory field, but core
	erpnext.update_child_qty_rate builds new child rows itself and has no
	way for us to pass custom_po_no through at insert time. We already
	enforce it's present via _validate_position_numbers_present() above, and
	apply the real values right after via _apply_position_numbers(), so it's
	safe to relax the DB-level mandatory check for the duration of this one
	call. Reverted in the finally block regardless of outcome."""

	custom_field_name = f"Sales Order Item-{POSITION_FIELDNAME}"
	frappe.db.set_value("Custom Field", custom_field_name, "reqd", 0, update_modified=False)
	frappe.clear_cache(doctype="Sales Order Item")
	try:
		yield
	finally:
		frappe.db.set_value("Custom Field", custom_field_name, "reqd", 1, update_modified=False)
		frappe.clear_cache(doctype="Sales Order Item")


def _apply_position_numbers(doc, child_docname, before_rows, incoming_items):
	"""Persist Pos. NO. (custom_po_no) values submitted via the Update Items
	dialog. Core erpnext.update_child_qty_rate does not carry custom fields
	through, so existing rows are matched by docname and newly inserted rows
	are matched positionally against the incoming rows that had no docname
	(core appends new rows in the same relative order it processes them)."""

	existing_by_docname = {
		row.get("docname"): row.get(POSITION_FIELDNAME)
		for row in incoming_items
		if row.get("docname")
	}
	new_row_position_numbers = [
		row.get(POSITION_FIELDNAME) for row in incoming_items if not row.get("docname") and row.get("item_code")
	]

	new_rows = [row for row in doc.get(child_docname, []) if row.name not in before_rows]

	for row in doc.get(child_docname, []):
		if row.name in existing_by_docname:
			position_number = existing_by_docname[row.name]
			if position_number and row.get(POSITION_FIELDNAME) != position_number:
				frappe.db.set_value(row.doctype, row.name, POSITION_FIELDNAME, position_number, update_modified=False)

	for row, position_number in zip(new_rows, new_row_position_numbers):
		if position_number:
			frappe.db.set_value(row.doctype, row.name, POSITION_FIELDNAME, position_number, update_modified=False)


def _get_changed_rows(before_rows, doc, child_docname, parent_doctype):
	changed_rows = []
	for row in doc.get(child_docname, []):
		after_snapshot = _build_row_snapshot(row, parent_doctype)
		before_snapshot = before_rows.get(row.name)

		if not before_snapshot:
			changed_rows.append(
				{
					"row_name": row.name,
					"old_values": {},
					"new_values": after_snapshot,
					"changed_fields": list(after_snapshot.keys()),
				}
			)
			continue

		changed_fields = [
			fieldname
			for fieldname, old_value in before_snapshot.items()
			if _normalize_value(old_value) != _normalize_value(after_snapshot.get(fieldname))
		]
		if changed_fields:
			changed_rows.append(
				{
					"row_name": row.name,
					"old_values": before_snapshot,
					"new_values": after_snapshot,
					"changed_fields": changed_fields,
				}
			)

	return changed_rows


def _normalize_value(value):
	if isinstance(value, float):
		return flt(value)
	return value


def _mark_rows_pending_approval(doc, changed_rows, parent_doctype, reason):
	child_doctype = ORDER_CONFIG[parent_doctype]["child_doctype"]
	now = frappe.utils.now()
	user = frappe.session.user

	for change in changed_rows:
		frappe.db.set_value(
			child_doctype,
			change["row_name"],
			{
				APPROVAL_STATUS_FIELD: PENDING_APPROVAL_STATUS,
				APPROVAL_REASON_FIELD: reason,
				APPROVAL_DATA_FIELD: frappe.as_json(
					{
						"action": change.get("action") or "update",
						"reason": reason,
						"requested_by": user,
						"requested_on": now,
						"changed_fields": change["changed_fields"],
						"old_values": change["old_values"],
						"new_values": change["new_values"],
					}
				),
			},
			update_modified=False,
		)


def _set_row_approval_status(doctype, rows, status):
	child_doctype = ORDER_CONFIG[doctype]["child_doctype"]
	for row in rows:
		frappe.db.set_value(
			child_doctype,
			row.name,
			{APPROVAL_STATUS_FIELD: status},
			update_modified=False,
		)


def _clear_row_approval_state(doctype, rows):
	child_doctype = ORDER_CONFIG[doctype]["child_doctype"]
	for row in rows:
		frappe.db.set_value(
			child_doctype,
			row.name,
			{
				APPROVAL_STATUS_FIELD: "",
				APPROVAL_REASON_FIELD: "",
				APPROVAL_DATA_FIELD: "",
			},
			update_modified=False,
		)


def _build_reverted_items_payload(doc, doctype, pending_rows):
	pending_by_name = {row.name: row for row in pending_rows}
	reverted_items = []

	for row in doc.get("items", []):
		pending_row = pending_by_name.get(row.name)
		if pending_row:
			request_data = _get_row_request_data(pending_row)
			old_values = request_data.get("old_values") or {}
			if not old_values:
				continue

			reverted_row = _build_row_snapshot(row, doctype)
			reverted_row["docname"] = row.name
			for fieldname, value in old_values.items():
				reverted_row[fieldname] = value
			reverted_items.append(reverted_row)
			continue

		current_row = _build_row_snapshot(row, doctype)
		current_row["docname"] = row.name
		reverted_items.append(current_row)

	return reverted_items


def _get_row_request_data(row):
	request_data = row.get(APPROVAL_DATA_FIELD)
	if not request_data:
		return {}

	try:
		return frappe.parse_json(request_data) or {}
	except Exception:
		return {}


def _log_item_update_rejection(doctype, docname, pending_rows, reason):
	request_reasons = []
	for row in pending_rows:
		request_data = _get_row_request_data(row)
		request_reason = request_data.get("reason") or row.get(APPROVAL_REASON_FIELD)
		if request_reason:
			request_reasons.append(_("Row {0}: {1}").format(row.idx, request_reason))

	reverted_row_details = _describe_pending_rows(doctype, pending_rows, reverse=True)

	comment_lines = [_("Pending item updates were rejected and reverted.")]
	if reason:
		comment_lines.append(_("Rejection reason: {0}").format(reason))
	if request_reasons:
		comment_lines.append(_("Original request reason(s): {0}").format(" | ".join(request_reasons)))
	if reverted_row_details:
		comment_lines.append(_("Reverted change(s): {0}").format(" | ".join(reverted_row_details)))

	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Comment",
		"reference_doctype": doctype,
		"reference_name": docname,
		"content": "<br>".join(comment_lines),
	}).insert(ignore_permissions=True)


def _log_item_update_request(doctype, docname, doc, changed_rows, reason):
	requester = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	row_descriptions = []
	items_by_name = {row.name: row for row in doc.get("items", [])}

	for change in changed_rows:
		row = items_by_name.get(change.get("row_name"))
		if not row:
			continue
		row_detail = _describe_request(doctype, row.idx, row.item_code, change)
		if row_detail:
			row_descriptions.append(row_detail)

	comment_lines = [
		_("Item update approval requested by {0}.").format(requester),
	]
	if reason:
		comment_lines.append(_("Reason: {0}").format(reason))
	if row_descriptions:
		comment_lines.append(_("Pending change(s): {0}").format(" | ".join(row_descriptions)))

	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Comment",
		"reference_doctype": doctype,
		"reference_name": docname,
		"content": "<br>".join(comment_lines),
	}).insert(ignore_permissions=True)


def _log_item_update_approval(doctype, docname, row_details):
	approver = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	comment_lines = [_("Pending item updates were approved by {0}.").format(approver)]
	if row_details:
		comment_lines.append(_("Approved change(s): {0}").format(" | ".join(row_details)))

	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Comment",
		"reference_doctype": doctype,
		"reference_name": docname,
		"content": "<br>".join(comment_lines),
	}).insert(ignore_permissions=True)


def _describe_request(doctype, row_idx, item_code, request_data, reverse=False):
	"""One-line summary of a row's request; reverse=True describes the revert."""
	if request_data.get("action") == ACTION_DELETE:
		label = _("Delete request withdrawn") if reverse else _("Delete requested")
		return _("Row {0} ({1}) - {2}").format(row_idx, item_code or _("Unknown Item"), label)

	old_values = request_data.get("old_values") or {}
	new_values = request_data.get("new_values") or {}
	if reverse:
		old_values, new_values = new_values, old_values

	return _format_change_details(doctype, row_idx, item_code, old_values, new_values)


def _describe_pending_rows(doctype, rows, reverse=False):
	details = [
		_describe_request(doctype, row.idx, row.item_code, _get_row_request_data(row), reverse=reverse)
		for row in rows
	]
	return [detail for detail in details if detail]


def _format_change_details(doctype, row_idx, item_code, old_values, new_values):
	field_labels = _get_snapshot_field_labels(doctype)
	details = []

	for fieldname, label in field_labels.items():
		old_value = old_values.get(fieldname)
		new_value = new_values.get(fieldname)
		if _normalize_value(old_value) == _normalize_value(new_value):
			continue
		details.append(
			_("{0}: {1} -> {2}").format(
				label,
				_format_snapshot_value(old_value),
				_format_snapshot_value(new_value),
			)
		)

	if not details:
		return ""

	return _("Row {0} ({1}) - {2}").format(
		row_idx,
		item_code or _("Unknown Item"),
		"; ".join(details),
	)


def _get_snapshot_field_labels(doctype):
	field_labels = {
		"item_code": _("Item Code"),
		"qty": _("Qty"),
		"rate": _("Rate"),
		"uom": _("UOM"),
		"conversion_factor": _("Conversion Factor"),
	}

	date_field = ORDER_CONFIG[doctype]["date_field"]
	field_labels[date_field] = _("Delivery Date") if doctype == "Sales Order" else _("Schedule Date")

	if doctype == "Purchase Order":
		field_labels["fg_item"] = _("Finished Good Item")
		field_labels["fg_item_qty"] = _("Finished Good Item Qty")

	return field_labels


def _format_snapshot_value(value):
	if value in (None, ""):
		return _("blank")
	if isinstance(value, float):
		return frappe.format_value(value, {"fieldtype": "Float"})
	return str(value)


def _log_reason(doctype, docname, reason):
	if not reason:
		return

	version_name = frappe.db.get_value(
		"Version",
		{"ref_doctype": doctype, "docname": docname},
		"name",
		order_by="creation desc",
	)
	if not version_name:
		return

	version = frappe.get_doc("Version", version_name)
	data = frappe.parse_json(version.data or "{}")
	data["reason"] = reason
	version.db_set("data", frappe.as_json(data), update_modified=False)


def _validate_sales_order_update_items_qty_lock(sales_order_name, incoming_items):
	sales_order = frappe.get_doc("Sales Order", sales_order_name)
	existing_items = {row.name: row for row in sales_order.get("items", [])}

	changed_rows = []
	for row in incoming_items:
		docname = row.get("docname")
		if not docname:
			continue

		existing_row = existing_items.get(docname)
		if not existing_row:
			continue

		qty = flt(row.get("qty"))
		if flt(existing_row.qty) != qty:
			changed_rows.append(
				{
					"row_idx": existing_row.idx,
					"item_code": existing_row.item_code,
					"old_qty": existing_row.qty,
					"new_qty": qty,
					"production_plan_qty": existing_row.production_plan_qty,
				}
			)

	if not changed_rows:
		return

	linked_plans_by_item = _get_linked_production_plans(
		sales_order_name, [row.name for row in sales_order.get("items", []) if flt(row.production_plan_qty) > 0]
	)

	locked_changes = []
	for row in changed_rows:
		if flt(row["production_plan_qty"]) > 0:
			linked_plans = ", ".join(linked_plans_by_item.get(row["item_code"], []))
			locked_changes.append(
				_("Row #{0} Item {1} qty cannot be changed from {2} to {3} because a Production Plan is linked against : {4}.").format(
					row["row_idx"],
					row["item_code"] or _("Unknown Item"),
					frappe.format_value(row["old_qty"], {"fieldtype": "Float"}),
					frappe.format_value(row["new_qty"], {"fieldtype": "Float"}),
					linked_plans or _("Production Plan linked"),
				)
			)

	if locked_changes:
		frappe.throw("<br>".join(locked_changes))


def _get_linked_production_plans(sales_order_name, sales_order_items):
	if not sales_order_items:
		return {}

	placeholders = ", ".join(["%s"] * len(sales_order_items))
	rows = frappe.db.sql(
		f"""
		SELECT
			ppi.sales_order_item,
			ppi.item_code,
			pp.name AS production_plan
		FROM `tabProduction Plan Item` ppi
		INNER JOIN `tabProduction Plan` pp ON pp.name = ppi.parent
		WHERE pp.docstatus = 1
			AND ppi.sales_order = %s
			AND ppi.sales_order_item IN ({placeholders})
		""",
		(sales_order_name, *sales_order_items),
		as_dict=True,
	)

	plans_by_item = {}
	for row in rows:
		plans_by_item.setdefault(row.item_code, set()).add(row.production_plan)

	return {item_code: sorted(plan_names) for item_code, plan_names in plans_by_item.items()}


def _notify_approvers(doctype, docname, doc, changed_rows, reason):
	"""Requester -> Super Approver: bell notification always, email too when an
	outgoing email account is set up."""

	approvers = frappe.get_all(
		"Has Role",
		filters={"role": APPROVER_ROLE, "parenttype": "User"},
		pluck="parent",
	)
	approvers = {user for user in approvers if user not in ("Administrator", "Guest", frappe.session.user)}
	if not approvers:
		return

	requester = _get_full_name(frappe.session.user)
	items_by_name = {row.name: row for row in doc.get("items", [])}
	row_details = []
	for change in changed_rows:
		row = items_by_name.get(change["row_name"])
		if row:
			row_details.append(_describe_request(doctype, row.idx, row.item_code, change))

	subject = _("{0} {1}: {2} item row(s) pending your approval").format(doctype, docname, len(changed_rows))
	intro = _("<b>{0}</b> has requested approval for item changes in <b>{1} {2}</b>.").format(
		frappe.utils.escape_html(requester), doctype, docname
	)
	_send_notifications(approvers, doctype, docname, subject, intro, row_details, reason, _("Reason"))


def _notify_requesters(doctype, docname, requesters, approved, row_details, reason=None):
	"""Super Approver -> the user(s) who raised the request."""

	recipients = {user for user in requesters if user and user not in ("Guest", frappe.session.user)}
	if not recipients:
		return

	approver = _get_full_name(frappe.session.user)
	decision = _("approved") if approved else _("rejected")
	subject = _("{0} {1}: your item update request was {2}").format(doctype, docname, decision)
	intro = _("<b>{0}</b> has {1} your item update request for <b>{2} {3}</b>.").format(
		frappe.utils.escape_html(approver), decision, doctype, docname
	)
	_send_notifications(recipients, doctype, docname, subject, intro, row_details, reason, _("Rejection Reason"))


def _get_requesters(rows):
	return {_get_row_request_data(row).get("requested_by") for row in rows} - {None}


def _get_full_name(user):
	return frappe.db.get_value("User", user, "full_name") or user


def _send_notifications(users, doctype, docname, subject, intro, row_details, reason, reason_label):
	reason_html = (
		f"<p><b>{reason_label}:</b> {frappe.utils.escape_html(reason)}</p>" if reason else ""
	)
	details_html = "".join(
		f"<li>{frappe.utils.escape_html(detail)}</li>" for detail in row_details
	)
	details_html = f"<ul>{details_html}</ul>" if details_html else ""

	doc_url = frappe.utils.get_url_to_form(doctype, docname)
	email_body = f"""
<p>Hello,</p>
<p>{intro}</p>
{reason_html}
{details_html}
<p><a href="{doc_url}" style="background:#4CAF50;color:white;padding:8px 16px;text-decoration:none;border-radius:4px;">Open {doctype}</a></p>
<p style="color:#888;font-size:12px;">This is an automated notification from Ujwal Industries ERP.</p>
"""

	enabled_users = frappe.get_all(
		"User",
		filters={"name": ["in", list(users)], "enabled": 1},
		fields=["name", "email"],
	)

	has_outgoing_email = bool(
		frappe.db.get_value("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name")
	)

	for user in enabled_users:
		# Bell icon notification
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": subject,
				"email_content": f"<p>{intro}</p>{reason_html}{details_html}",
				"for_user": user.name,
				"from_user": frappe.session.user,
				"document_type": doctype,
				"document_name": docname,
				"type": "Alert",
			}
		).insert(ignore_permissions=True)

		# Email notification (only if outgoing email account is configured)
		if has_outgoing_email and user.email:
			frappe.sendmail(
				recipients=[user.email],
				subject=subject,
				message=email_body,
				reference_doctype=doctype,
				reference_name=docname,
				now=True,
			)
