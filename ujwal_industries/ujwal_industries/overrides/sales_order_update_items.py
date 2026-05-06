import json

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.controllers.accounts_controller import update_child_qty_rate as erpnext_update_child_qty_rate


ORDER_CONFIG = {
	"Sales Order": {
		"child_doctype": "Sales Order Item",
		"date_field": "delivery_date",
		"approval_roles": {"Sales Manager", "System Manager"},
	},
	"Purchase Order": {
		"child_doctype": "Purchase Order Item",
		"date_field": "schedule_date",
		"approval_roles": {"Purchase Manager", "System Manager"},
	},
}

APPROVAL_STATUS_FIELD = "custom_update_approval_status"
APPROVAL_REASON_FIELD = "custom_update_request_reason"
APPROVAL_DATA_FIELD = "custom_update_request_data"
PENDING_APPROVAL_STATUS = "Pending Approval"
APPROVED_STATUS = "Approved"


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

	_ensure_no_pending_item_approvals(doc, child_docname)
	_ensure_no_item_deletions(doc, child_docname, incoming_items)

	if parent_doctype == "Sales Order":
		_validate_sales_order_update_items_qty_lock(parent_doctype_name, incoming_items)

	before_rows = _get_row_snapshots(doc, child_docname, parent_doctype)

	result = erpnext_update_child_qty_rate(
		parent_doctype=parent_doctype,
		trans_items=trans_items,
		parent_doctype_name=parent_doctype_name,
		child_docname=child_docname,
	)

	updated_doc = frappe.get_doc(parent_doctype, parent_doctype_name)
	changed_rows = _get_changed_rows(before_rows, updated_doc, child_docname, parent_doctype)

	if changed_rows:
		_mark_rows_pending_approval(updated_doc, changed_rows, parent_doctype, reason)
		_log_reason(parent_doctype, parent_doctype_name, reason)
		_log_item_update_request(parent_doctype, parent_doctype_name, updated_doc, changed_rows, reason)
		_notify_approvers(parent_doctype, parent_doctype_name, changed_rows, reason)

	return result


@frappe.whitelist()
def approve_pending_item_updates(doctype, docname):
	if doctype not in ORDER_CONFIG:
		frappe.throw(_("Approval is only supported for Sales Order and Purchase Order item updates."))

	_ensure_approval_permission(doctype)

	doc = frappe.get_doc(doctype, docname)
	pending_rows = _get_pending_rows(doc)

	if not pending_rows:
		frappe.msgprint(_("There are no pending item updates to approve."))
		return

	_set_row_approval_status(doctype, pending_rows, APPROVED_STATUS)

	frappe.msgprint(_("Pending item updates approved successfully."))


@frappe.whitelist()
def reject_pending_item_updates(doctype, docname, reason=None):
	if doctype not in ORDER_CONFIG:
		frappe.throw(_("Approval is only supported for Sales Order and Purchase Order item updates."))

	_ensure_approval_permission(doctype)

	doc = frappe.get_doc(doctype, docname)
	pending_rows = _get_pending_rows(doc)

	if not pending_rows:
		frappe.msgprint(_("There are no pending item updates to reject."))
		return

	reverted_items = _build_reverted_items_payload(doc, doctype, pending_rows)

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

	reverted_doc = frappe.get_doc(doctype, docname)
	reverted_names = {row.name for row in reverted_doc.get("items", [])}
	remaining_pending_rows = [row for row in pending_rows if row.name in reverted_names]
	_clear_row_approval_state(doctype, remaining_pending_rows)
	_log_item_update_rejection(doctype, docname, pending_rows, reason)

	frappe.msgprint(_("Pending item updates rejected and reverted successfully."))


def _ensure_approval_permission(doctype):
	if frappe.session.user == "Administrator":
		return

	allowed_roles = ORDER_CONFIG[doctype]["approval_roles"]
	if not allowed_roles.intersection(set(frappe.get_roles())):
		frappe.throw(_("You are not allowed to approve pending item updates for {0}.").format(doctype))


def _ensure_no_pending_item_approvals(doc, child_docname):
	pending_rows = [row.idx for row in doc.get(child_docname, []) if row.get(APPROVAL_STATUS_FIELD) == PENDING_APPROVAL_STATUS]
	if pending_rows:
		row_list = ", ".join(str(idx) for idx in pending_rows)
		frappe.throw(
			_("Row(s) {0} are already pending approval. Approve them before making another item update.").format(row_list)
		)


def _get_pending_rows(doc, child_docname="items"):
	return [row for row in doc.get(child_docname, []) if row.get(APPROVAL_STATUS_FIELD) == PENDING_APPROVAL_STATUS]


def _ensure_no_item_deletions(doc, child_docname, incoming_items):
	existing_docnames = {row.name for row in doc.get(child_docname, [])}
	incoming_docnames = {row.get("docname") for row in incoming_items if row.get("docname")}
	missing_docnames = existing_docnames - incoming_docnames
	if missing_docnames:
		frappe.throw(_("Deleting items through this approval flow is not supported."))


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
	reverted_row_details = []
	for row in pending_rows:
		request_data = _get_row_request_data(row)
		request_reason = request_data.get("reason") or row.get(APPROVAL_REASON_FIELD)
		if request_reason:
			request_reasons.append(_("Row {0}: {1}").format(row.idx, request_reason))

		row_detail = _format_change_details(
			doctype,
			row.idx,
			row.item_code,
			request_data.get("new_values") or {},
			request_data.get("old_values") or {},
		)
		if row_detail:
			reverted_row_details.append(row_detail)

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
		row_detail = _format_change_details(
			doctype,
			row.idx,
			row.item_code,
			change.get("old_values") or {},
			change.get("new_values") or {},
		)
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


def _notify_approvers(doctype, docname, changed_rows, reason):
	approval_roles = ORDER_CONFIG[doctype]["approval_roles"]

	approvers = frappe.get_all(
		"Has Role",
		filters={"role": ("in", list(approval_roles)), "parenttype": "User"},
		fields=["parent as user", "parent as email"],
		pluck="user",
	)
	approvers = list(
		{u for u in approvers if u not in ("Administrator", "Guest", frappe.session.user)}
	)

	if not approvers:
		return

	requester = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	row_count = len(changed_rows)
	reason_text = f" — Reason: {reason}" if reason else ""

	subject = _("{0} {1}: {2} item row(s) pending your approval").format(
		doctype, docname, row_count
	)
	plain_message = _(
		"{0} updated {1} item row(s) in {2} {3} and the change requires approval.{4}"
	).format(requester, row_count, doctype, docname, reason_text)

	doc_url = frappe.utils.get_url_to_form(doctype, docname)

	# Build change detail rows for the email table
	change_rows_html = ""
	for row in changed_rows:
		data = {}
		try:
			raw = frappe.db.get_value(
				ORDER_CONFIG[doctype]["child_doctype"],
				row,
				APPROVAL_DATA_FIELD,
			)
			if raw:
				import json as _json
				data = _json.loads(raw)
		except Exception:
			pass
		changed_fields = ", ".join(data.get("changed_fields", [])) or "—"
		item_code = data.get("new_values", {}).get("item_code", "") or row
		change_rows_html += f"<tr><td style='padding:4px 8px;border:1px solid #ddd;'>{item_code}</td><td style='padding:4px 8px;border:1px solid #ddd;'>{changed_fields}</td></tr>"

	email_body = f"""
<p>Hello,</p>
<p><b>{requester}</b> has requested approval for changes in <b>{doctype} {docname}</b>.</p>
{"<p><b>Reason:</b> " + reason + "</p>" if reason else ""}
<table style="border-collapse:collapse;width:100%;margin:12px 0;">
  <thead>
    <tr style="background:#f5f5f5;">
      <th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Item</th>
      <th style="padding:6px 8px;border:1px solid #ddd;text-align:left;">Changed Fields</th>
    </tr>
  </thead>
  <tbody>
    {change_rows_html if change_rows_html else "<tr><td colspan='2' style='padding:6px 8px;border:1px solid #ddd;'>" + str(row_count) + " row(s) updated</td></tr>"}
  </tbody>
</table>
<p><a href="{doc_url}" style="background:#4CAF50;color:white;padding:8px 16px;text-decoration:none;border-radius:4px;">Open {doctype}</a></p>
<p style="color:#888;font-size:12px;">This is an automated notification from Ujwal Industries ERP.</p>
"""

	approver_emails = frappe.get_all(
		"User",
		filters={"name": ["in", approvers], "enabled": 1},
		fields=["name", "email"],
	)

	has_outgoing_email = bool(frappe.db.get_value(
		"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
	))

	for approver in approver_emails:
		# Bell icon notification
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": subject,
				"email_content": plain_message,
				"for_user": approver["name"],
				"document_type": doctype,
				"document_name": docname,
				"type": "Alert",
			}
		).insert(ignore_permissions=True)

		# Email notification (only if outgoing email account is configured)
		if has_outgoing_email and approver.get("email"):
			frappe.sendmail(
				recipients=[approver["email"]],
				subject=subject,
				message=email_body,
				reference_doctype=doctype,
				reference_name=docname,
				now=True,
			)
