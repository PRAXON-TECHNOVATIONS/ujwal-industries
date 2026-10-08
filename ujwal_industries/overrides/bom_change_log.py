# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Server-side Change Log for BOM.

Diffs the incoming BOM against the last saved version on every update and
writes the differences into doc.change_log (BOM Change Log child table).
This runs regardless of how the edit was made (form, bulk edit, API, import),
unlike a client-side field-trigger approach which only catches interactive
form edits and can miss rows added via linked-field selection or bulk tools.
"""

import frappe
from frappe.utils import cstr

PARENT_IGNORE_FIELDS = {
	"name", "owner", "creation", "modified", "modified_by", "idx", "docstatus",
	"change_log", "workflow_state", "amended_from", "lft", "rgt", "old_parent",
	"_user_tags", "_comments", "_assign", "_liked_by",
	# Pure cost rollups recomputed from Items/Scrap Items/Operations -- the row-level
	# diff on those tables already explains why these moved, so logging them too
	# would just be a noisy duplicate of the same underlying edit.
	"raw_material_cost", "base_raw_material_cost",
	"scrap_material_cost", "base_scrap_material_cost",
	"operating_cost", "base_operating_cost",
	"total_cost", "base_total_cost",
}

CHILD_TABLES = {
	"items": {"doctype": "BOM Item", "label": "Items"},
	"scrap_items": {"doctype": "BOM Scrap Item", "label": "Scrap Items"},
	"operations": {"doctype": "BOM Operation", "label": "Operations"},
}

CHILD_IGNORE_FIELDS = {
	"name", "owner", "creation", "modified", "modified_by", "idx", "docstatus",
	"parent", "parentfield", "parenttype",
	# Pure derivatives of other fields already logged on the same row
	# (amount = qty * rate, operating_cost/cost_per_unit = hour_rate * time_in_mins).
	"amount", "base_amount",
	"operating_cost", "base_operating_cost", "cost_per_unit", "base_cost_per_unit",
	"stock_qty", "qty_consumed_per_unit",
}


def _format_value(df, value):
	if value in (None, ""):
		return ""
	if df and df.fieldtype == "Check":
		return "Yes" if cstr(value) == "1" else "No"
	if df and df.fieldtype in ("Currency", "Float", "Percent", "Int"):
		return frappe.format_value(value, df)
	return cstr(value)


def _add_log_row(doc, label, old_value, new_value, df=None):
	old_fmt = _format_value(df, old_value)
	new_fmt = _format_value(df, new_value)
	if old_fmt == new_fmt:
		return

	row = doc.append("change_log", {})
	row.filed_name = label
	row.old_value = old_fmt
	row.new_value = new_fmt


def _diff_parent_fields(doc, before):
	meta = doc.meta
	for df in meta.fields:
		if df.fieldtype in ("Section Break", "Column Break", "Tab Break", "Table", "HTML", "Button"):
			continue
		if df.fieldname in PARENT_IGNORE_FIELDS:
			continue

		old_value = before.get(df.fieldname)
		new_value = doc.get(df.fieldname)
		if old_value == new_value:
			continue

		label = df.label or df.fieldname
		_add_log_row(doc, label, old_value, new_value, df)


def _diff_child_table(doc, before, fieldname, table_meta):
	child_doctype = table_meta["doctype"]
	table_label = table_meta["label"]
	child_meta = frappe.get_meta(child_doctype)

	before_rows_by_name = {row.name: row for row in (before.get(fieldname) or [])}
	current_rows = doc.get(fieldname) or []
	current_names = set()

	for row in current_rows:
		current_names.add(row.name)
		before_row = before_rows_by_name.get(row.name)

		if not before_row:
			identifier = row.get("item_code") or row.get("operation") or row.name
			_add_log_row(
				doc,
				f"{table_label} → Row {row.idx} → Added",
				None,
				identifier,
			)
			continue

		for df in child_meta.fields:
			if df.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Button"):
				continue
			if df.fieldname in CHILD_IGNORE_FIELDS:
				continue

			old_value = before_row.get(df.fieldname)
			new_value = row.get(df.fieldname)
			if old_value == new_value:
				continue

			label = df.label or df.fieldname
			_add_log_row(
				doc,
				f"{table_label} → Row {row.idx} → {label}",
				old_value,
				new_value,
				df,
			)

	for name, before_row in before_rows_by_name.items():
		if name in current_names:
			continue
		identifier = before_row.get("item_code") or before_row.get("operation") or name
		_add_log_row(
			doc,
			f"{table_label} → Row {before_row.idx} → Removed",
			identifier,
			None,
		)


def track_changes(doc, method):
	if doc.is_new():
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	_diff_parent_fields(doc, before)

	for fieldname, table_meta in CHILD_TABLES.items():
		_diff_child_table(doc, before, fieldname, table_meta)
