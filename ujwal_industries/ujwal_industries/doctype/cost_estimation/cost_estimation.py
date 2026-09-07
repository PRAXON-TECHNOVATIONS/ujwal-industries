# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


def get_last_purchase_rate(item_code):
	return flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))


def get_item_name(item_code):
	return frappe.db.get_value("Item", item_code, "item_name")


def get_last_sales_rate(item_code):
	rate = frappe.db.get_value(
		"Sales Invoice Item",
		{"item_code": item_code, "docstatus": 1},
		"rate",
		order_by="creation desc",
	)
	return flt(rate)


@frappe.whitelist()
def get_last_sales_rate_api(item_code):
	return get_last_sales_rate(item_code)


def get_subcontract_operation_row(item_code, company=None):
	"""If this item has a subcontract row set up on its Item master
	(Purchasing tab → Subcontracting Suppliers, Type = Subcontract, with an
	Operation and Rate per Pc filled in), return it as an Operations row dict
	— since subcontracted steps like Case Hardening or Plating often have no
	BOM Operation of their own (they're bought-in services, not in-house
	machine time). Only one row per (item, company) can be marked Is Default,
	so when `company` is given, this matches strictly on that company — no
	cross-company fallback, since showing a different company's rate/supplier
	would be worse than showing none. Without a company, prefers the row
	marked Is Default across all companies; falls back to the first row that
	has both Operation and Rate set. Returns None if nothing matches."""
	filters = {
		"parent": item_code,
		"parenttype": "Item",
		"custom_type": "Subcontract",
		"custom_operation": ["is", "set"],
	}
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"Item Subcontracting Supplier",
		filters=filters,
		fields=["custom_operation", "custom_rate_per_pc", "is_default"],
		order_by="is_default desc",
	)
	row = next((r for r in rows if flt(r.custom_rate_per_pc)), None)
	if not row:
		return None

	return {
		"operation": row.custom_operation,
		"workstation": None,
		"time_per_pc_min": 0,
		"rate_per_pc": flt(row.custom_rate_per_pc),
	}


def first_workstation_from_csv(csv_value):
	"""BOM Operation can list several interchangeable machines in
	custom_workstations_csv (e.g. 'UI/MC/94,UI/MC/95,...') when the standard
	single workstation field is left empty. Default to the first one listed
	— the pulled row stays editable if a different machine should be used
	for this estimate."""
	if not csv_value:
		return None
	return csv_value.split(",")[0].strip()


def compute_rate_per_pc(shift_rate_per_min, time_per_pc_min, no_of_cavities=None, qty_multiplier=None):
	"""Rate/Pc = Shift Rate per Min ÷ Per Min/Pc, then divided by the tool's
	No of Cavities when one strike of the tool makes more than one piece
	(e.g. a 10-cavity mould makes 10 pcs per cycle, so machine time is shared
	across all 10). A missing or zero cavity count means no tool is in use
	for this operation, so the rate is left undivided.

	The result is then multiplied by `qty_multiplier` (default 1, no
	effect) — used for the opposite situation: a hand-assembly operation
	that consumes several of ONE sub-component per parent unit (e.g. 700 of
	one part, 100 of another going into the same assembly) isn't one action
	regardless of quantity the way a machine cycle is, so its per-piece cost
	is scaled UP by how many of that component are used, not divided down.
	See explode_bom_tree's Assembly fan-out and Ujwal Industries Setting →
	Assembly Operation Names."""
	if not flt(time_per_pc_min):
		return 0
	rate = flt(shift_rate_per_min) / flt(time_per_pc_min)
	cavities = flt(no_of_cavities)
	if cavities:
		rate = rate / cavities
	multiplier = flt(qty_multiplier) or 1
	if multiplier != 1:
		rate = rate * multiplier
	return rate


def compute_assembly_breakdown_rate(shift_rate_per_min, time_per_pc_min, no_of_cavities, breakdown):
	"""For a single Assembly-type operation row that consumes several
	manufactured sub-parts (breakdown = the parsed assembly_breakdown_json
	list), the row's own Rate/Pc is the SUM of (this operation's per-cavity
	base rate × each sub-part's own qty_multiplier) — the physical assembly
	step is one action, but its cost still reflects putting in 700 of one
	part and 100 of another, not treating them as equal. Uses
	compute_rate_per_pc with qty_multiplier=1 to get the shared base rate
	once, then applies each entry's multiplier to that same base."""
	base_rate = compute_rate_per_pc(shift_rate_per_min, time_per_pc_min, no_of_cavities)
	total = sum(base_rate * flt(entry.get("qty_multiplier")) for entry in breakdown or [])
	return total


def get_assembly_operation_names():
	"""BOM Operation names (from Ujwal Industries Setting) that mean 'put
	several manufactured sub-parts together by hand, one at a time' rather
	than 'one machine cycle produces one output' — e.g. Assembly. These get
	fanned out per sub-component in explode_bom_tree instead of costed once
	per parent unit, since assembling a unit that contains 700 of one
	sub-part and 100 of another is 700+100 individual assembly actions, not
	one action regardless of how many parts go in."""
	raw = frappe.db.get_single_value("Ujwal Industries Setting", "assembly_operation_names") or ""
	return {name.strip() for name in raw.split(",") if name.strip()}


def get_default_tool_for_operation(bom_doc, operation):
	"""BOM's Tool Details table (custom_tool_details) can list several tools
	against the same Operation (e.g. alternate moulds) — only the one marked
	Is Default is the one this estimate should cost against. Returns None if
	no row is marked default for this operation, so the caller doesn't divide
	by a tool that isn't actually in use."""
	if not operation:
		return None
	for row in bom_doc.get("custom_tool_details") or []:
		if row.operation == operation and row.is_default and row.tool:
			return row.tool
	return None


def explode_bom_tree(bom_name, per_pc_qty=1, company=None, estimate_qty=None):
	"""Walk this BOM and every sub-assembly BOM beneath it, returning
	flattened RM/Scrap/Operation rows (plain dicts, not appended to any
	document) scaled to `per_pc_qty` — how many units of *this* BOM's item
	are needed per one finished piece of the top-level item. A sub-assembly's
	own subcontract step (e.g. Case Hardening on item 200632) is the
	operation that turns whatever its own BOM tree produces INTO that item,
	so it's added right after that tree is walked — Operations land in real
	process order (raw material's operations first, each subcontract step
	right after the tree beneath it, working up).

	RM/Scrap weight is each row's OWN `stock_qty`, taken as-is from wherever
	it sits in the tree — deliberately NOT multiplied by the consumption
	ratio of any assembly level above it (see the "no intermediate-level
	compounding" comment at the rm_items.append() call below for the full
	rationale and a worked example). `estimate_qty` then scales that raw
	weight to the estimate's own header Quantity, RELATIVE TO THE TOP-LEVEL
	BOM's OWN reference batch size (`bom.quantity`) — e.g. if
	BOM-300189-001's own quantity is 100 and item 100118's own row shows
	2.21 Kg, then `estimate_qty=100` must reproduce 2.21 unchanged, and
	`estimate_qty=200` must give 4.42 (2.21 * 200/100). This is applied only
	to RM/Scrap, once, AFTER the walk — never threaded into the recursion
	(which uses `per_pc_qty` only for Operations' cycle-time fallback,
	unrelated to the estimate's own Quantity) — and never applied to
	Operations, since machine cycle time per piece is intrinsic to the
	operation and doesn't change with how many pieces this estimate happens
	to be quoting. Pass None (the default) to skip scaling entirely, e.g.
	for the plain per-1-piece pull used internally by `get_bom_explosion`'s
	callers before a Quantity is known.

	Every operation row is also tagged with `item` (the item the operation is
	performed on) and `parent_item` (the assembly item whose BOM consumes
	that item — blank for the top-level item itself), so the Summary can
	render Operations as a nested BOM tree instead of a flat list. Alongside
	that, `item_tree_edges` records an (item, parent_item) pair for EVERY
	item visited by the walk — including ones with no operations of their
	own (pure-container assemblies, e.g. one that only exists to group other
	sub-assemblies) — so the full nesting structure can still be
	reconstructed even where operation rows alone would leave a gap."""
	rm_items = []
	scrap_items = []
	operation_items = []
	item_tree_edges = []

	def _walk(bom_name, per_pc_qty, parent_item=None):
		bom = frappe.get_doc("BOM", bom_name)
		batch_qty = flt(bom.quantity) or 1
		this_item = bom.item
		item_tree_edges.append((this_item, parent_item))

		for row in bom.items:
			if row.bom_no:
				# per_pc_qty still threads through recursion for Operations'
				# cycle-time fallback below (unaffected by this change) — but
				# RM/Scrap no longer compound this ratio at all, see the
				# gross_wt_per_pc/scrap_wt_per_pc comment below.
				row_qty_per_pc = flt(row.stock_qty) * per_pc_qty / batch_qty
				_walk(row.bom_no, row_qty_per_pc, parent_item=this_item)
			else:
				# gross_wt_per_pc is this row's OWN stock_qty, taken as-is —
				# deliberately NOT multiplied by the consumption ratio of any
				# assembly above it in the tree. E.g. item 100118 sits inside
				# BOM-200122-001 (stock_qty=2.21 Kg there), which is itself
				# consumed 1300-per-100 by the top BOM — but Cost Estimation
				# does NOT multiply 2.21 by that 1300/100 ratio; it uses 2.21
				# directly, exactly matching what the BOM tree view shows at
				# item 100118's own row. Confirmed explicitly by the user
				# after the tree's own qty field was corrected to 2.21 (see
				# fix_bom_200122_item_qty patch) — only `estimate_qty` (the
				# Cost Estimation header Quantity, applied once after the
				# walk, see below) scales this number, never intermediate
				# BOM levels' own consumption counts.
				rm_items.append(
					{
						"rm_used": row.item_code,
						"item_name": get_item_name(row.item_code),
						"rm_rate_per_kg": get_last_purchase_rate(row.item_code),
						"gross_wt_per_pc": flt(row.stock_qty),
						"bom": bom_name,
					}
				)
			subcontract_row = get_subcontract_operation_row(row.item_code, company=company)
			if subcontract_row:
				subcontract_row["item"] = row.item_code
				subcontract_row["item_name"] = get_item_name(row.item_code)
				subcontract_row["parent_item"] = this_item
				operation_items.append(subcontract_row)

		for row in bom.scrap_items:
			# Same "own row's stock_qty, no intermediate-level compounding"
			# rule as RM above.
			scrap_items.append(
				{
					"scrap_description": row.item_code,
					"item_name": get_item_name(row.item_code),
					"scrap_rate_per_kg": get_last_sales_rate(row.item_code),
					"scrap_wt_per_pc": flt(row.stock_qty),
					"bom": bom_name,
				}
			)

		for row in bom.operations:
			# "Per Min / Pc" on this doctype is a PRODUCTION RATE (pieces made
			# per minute) — since Rate/Pc = Shift Rate per Min ÷ Per Min/Pc.
			# BOM Operation's own custom_batchsize field already holds this
			# rate directly (pieces/min for that operation+machine) and is
			# NOT scaled by the estimate's batch qty — it's an intrinsic
			# property of the operation, not a quantity that grows with how
			# many finished pieces we're costing. Only fall back to deriving
			# it from time_in_mins (a per-piece cycle time in minutes, so its
			# reciprocal is pieces/min) when Batch Size isn't filled in.
			if flt(row.custom_batchsize):
				time_per_pc_min = flt(row.custom_batchsize)
			else:
				cycle_time_per_pc_min = flt(row.time_in_mins) * per_pc_qty / batch_qty
				time_per_pc_min = 1 / cycle_time_per_pc_min if cycle_time_per_pc_min else 0
			workstation = row.workstation or first_workstation_from_csv(row.custom_workstations_csv)

			operation_row = {
				"item": this_item,
				"item_name": get_item_name(this_item),
				"parent_item": parent_item,
				"operation": row.operation,
				"workstation": workstation,
				"time_per_pc_min": time_per_pc_min,
				# How many of `this_item` are needed per ONE finished piece of
				# the top-level item — per_pc_qty already IS this number by
				# construction (it's threaded down through the recursion,
				# see row_qty_per_pc above), so it's used as-is, applied here
				# to every operation on this item, not just Assembly-named
				# ones. At the top level per_pc_qty=1 (the item's own
				# operations happen once per finished piece); at a nested
				# level it's that item's own consumption count (e.g. 13 for
				# an item the parent BOM uses 1300-per-100).
				"qty_multiplier": flt(per_pc_qty),
			}
			if workstation:
				operation_row["shift_rate_per_min"] = frappe.db.get_value(
					"Workstation", workstation, "custom_cost_per_min"
				)
				asset = frappe.db.get_value("Workstation", workstation, "custom_asset_name")
				operation_row["machine_name"] = (
					frappe.db.get_value("Asset", asset, "asset_name") if asset else None
				)

			tool = get_default_tool_for_operation(bom, row.operation)
			if tool:
				operation_row["tool"] = tool
				operation_row["no_of_cavities"] = frappe.db.get_value(
					"Asset", tool, "custom_no_of_cavities"
				)

			operation_items.append(operation_row)

	_walk(bom_name, per_pc_qty)

	if estimate_qty is not None:
		top_bom_batch_qty = flt(frappe.db.get_value("BOM", bom_name, "quantity")) or 1
		qty_multiplier = (flt(estimate_qty) or top_bom_batch_qty) / top_bom_batch_qty
		if qty_multiplier != 1:
			for row in rm_items:
				row["gross_wt_per_pc"] = flt(row["gross_wt_per_pc"]) * qty_multiplier
			for row in scrap_items:
				row["scrap_wt_per_pc"] = flt(row["scrap_wt_per_pc"]) * qty_multiplier

	return {
		"rm_items": rm_items,
		"scrap_items": scrap_items,
		"operation_items": operation_items,
		"item_tree_edges": item_tree_edges,
	}


@frappe.whitelist()
def get_bom_explosion(bom, item=None, company=None, qty=1):
	"""Stateless version of the BOM pull — callable before the Cost
	Estimation document is even saved, so the browser can populate RM/Scrap/
	Operations live as soon as an Item (and its default BOM) is picked, with
	no button and no save round-trip required."""
	if not bom:
		frappe.throw(_("BOM is required."))

	data = explode_bom_tree(bom, per_pc_qty=1, company=company, estimate_qty=flt(qty) or 1)
	if item:
		# The finished item's own subcontract step (if any) is the very last
		# thing that happens to it, after everything the BOM tree produces.
		trailing = get_subcontract_operation_row(item, company=company)
		if trailing:
			trailing["item"] = item
			trailing["parent_item"] = None
			data["operation_items"].append(trailing)
	return data


def _merge_bom_rows(existing_rows, fresh_rows, match_fields, preserve_fields):
	"""Reconciles a child table against a fresh BOM pull instead of wiping
	and replacing it outright: a row already present (by `match_fields`) is
	kept and has every field except `preserve_fields` refreshed to the fresh
	value — so a manually-typed rate survives, but anything that describes
	the BOM's own structure (weight, cycle time, tool, machine, item name...)
	catches up to what the BOM says now. A row with no match in the fresh
	pull is dropped (the BOM no longer produces it), and a fresh row with no
	match in existing is appended as new. Returns the new list of row dicts;
	does not touch the document itself."""

	def key(row):
		return tuple(row.get(f) for f in match_fields)

	existing_by_key = {}
	for row in existing_rows:
		existing_by_key.setdefault(key(row), []).append(row)

	merged = []
	for fresh_row in fresh_rows:
		bucket = existing_by_key.get(key(fresh_row))
		if bucket:
			old_row = bucket.pop(0)
			new_row = dict(fresh_row)
			for f in preserve_fields:
				if old_row.get(f):
					new_row[f] = old_row.get(f)
			merged.append(new_row)
		else:
			merged.append(dict(fresh_row))

	return merged


@frappe.whitelist()
def sync_rm_items(cost_estimation):
	"""Reconciles just the RM table against a fresh pull from the current
	BOM — adds components the BOM now has that this estimate doesn't, drops
	ones the BOM no longer has, and on a still-present row keeps whatever
	Rate/Kg was typed in (a manual override or a prior fetched last-purchase
	rate) while refreshing everything else (weight, item name, source BOM)
	to match the BOM's current structure."""
	doc = frappe.get_doc("Cost Estimation", cost_estimation)
	if not doc.bom:
		frappe.throw(_("Set a BOM before syncing."))

	fresh = explode_bom_tree(doc.bom, per_pc_qty=1, company=doc.company, estimate_qty=flt(doc.qty) or 1)
	merged = _merge_bom_rows(
		[row.as_dict() for row in doc.rm_items],
		fresh["rm_items"],
		match_fields=["rm_used", "bom"],
		preserve_fields=["rm_rate_per_kg"],
	)
	doc.rm_items = []
	for row in merged:
		doc.append("rm_items", row)
	doc.save()
	return {"count": len(merged)}


@frappe.whitelist()
def sync_scrap_items(cost_estimation):
	"""Same reconciliation as sync_rm_items, for the Scrap table — keeps a
	manually set/overridden Scrap Rate/Kg on rows still produced by the BOM,
	refreshes weight/item name/source BOM, adds new scrap the BOM now
	produces, drops scrap it no longer does."""
	doc = frappe.get_doc("Cost Estimation", cost_estimation)
	if not doc.bom:
		frappe.throw(_("Set a BOM before syncing."))

	fresh = explode_bom_tree(doc.bom, per_pc_qty=1, company=doc.company, estimate_qty=flt(doc.qty) or 1)
	merged = _merge_bom_rows(
		[row.as_dict() for row in doc.scrap_items],
		fresh["scrap_items"],
		match_fields=["scrap_description", "bom"],
		preserve_fields=["scrap_rate_per_kg"],
	)
	doc.scrap_items = []
	for row in merged:
		doc.append("scrap_items", row)
	doc.save()
	return {"count": len(merged)}


@frappe.whitelist()
def sync_operation_items(cost_estimation):
	"""Same reconciliation as sync_rm_items, for the Operations table —
	matched by (item, operation) since that's what's stable across a BOM
	edit, unlike workstation/tool/rate which can change. Keeps a manually
	set/overridden Rate/Pc on rows still present in the BOM, refreshes
	machine/tool/cavities/cycle time, adds operations newly in the BOM,
	drops ones no longer there (including the top-level item's own trailing
	subcontract step, re-derived fresh every sync)."""
	doc = frappe.get_doc("Cost Estimation", cost_estimation)
	if not doc.bom:
		frappe.throw(_("Set a BOM before syncing."))

	fresh = explode_bom_tree(doc.bom, per_pc_qty=1, company=doc.company)
	if doc.item:
		trailing = get_subcontract_operation_row(doc.item, company=doc.company)
		if trailing:
			trailing["item"] = doc.item
			trailing["parent_item"] = None
			fresh["operation_items"].append(trailing)

	merged = _merge_bom_rows(
		[row.as_dict() for row in doc.operation_items],
		fresh["operation_items"],
		match_fields=["item", "operation"],
		preserve_fields=["rate_per_pc"],
	)
	doc.operation_items = []
	for row in merged:
		doc.append("operation_items", row)
	doc.item_tree_json = frappe.as_json(fresh["item_tree_edges"])
	doc.save()
	return {"count": len(merged)}


@frappe.whitelist()
def sync_all_tables(cost_estimation):
	"""Runs all three table syncs in one call — RM/Scrap/Operations each
	reconciled independently against the current BOM, same merge semantics
	as the individual sync_*_items calls."""
	rm = sync_rm_items(cost_estimation)
	scrap = sync_scrap_items(cost_estimation)
	operations = sync_operation_items(cost_estimation)
	return {"rm": rm, "scrap": scrap, "operations": operations}


def get_top_level_item_for_subcontract_order(subcontracting_order):
	"""A Subcontracting Order is raised for an intermediate item (e.g. 200632,
	Case Hardened) — but the ordered Operations sequence with that step's
	position in it only exists on the Cost Estimation of the top-level
	sellable item (e.g. 300918), since Cost Estimation explodes one item's
	whole BOM tree into a single flat, ordered list. Trace back through the
	documents that created this demand to find that top-level item:
	Subcontracting Order → its Purchase Order → each PO Item's Production
	Plan → that plan's own item_code (the finished item actually being
	planned for). Returns None if the chain is broken anywhere (e.g. a
	manually created Subcontracting Order with no Production Plan behind it)."""
	po = frappe.db.get_value("Subcontracting Order", subcontracting_order, "purchase_order")
	if not po:
		return None

	production_plan = frappe.db.get_value(
		"Purchase Order Item", {"parent": po, "production_plan": ["is", "set"]}, "production_plan"
	)
	if not production_plan:
		return None

	return frappe.db.get_value("Production Plan Item", {"parent": production_plan}, "item_code")


@frappe.whitelist()
def get_subcontract_annexure_rate(item_code, company=None, subcontracting_order=None):
	"""Per-piece cost to show on a "Send to Subcontractor" Stock Entry row for
	`item_code` — the item being received back from the subcontractor (e.g.
	200632, Case Hardened), not the raw material physically sent out. Which
	operation this shipment represents is read off item_code's own default
	Subcontract row (Item Subcontracting Supplier, same place its rate lives).
	The cost is Net RM Cost/Pc + the Rate/Pc of every operation that comes
	BEFORE that operation in the latest submitted Cost Estimation of the
	TOP-LEVEL finished item this subcontract order was raised for (traced via
	get_top_level_item_for_subcontract_order) — i.e. everything already spent
	on this piece up to the point it's handed to this subcontractor. Returns
	None if item_code has no subcontract row, the top-level item can't be
	traced, or no submitted Cost Estimation exists for it."""
	subcontract_row = get_subcontract_operation_row(item_code, company=company)
	if not subcontract_row or not subcontract_row.get("operation"):
		return None
	target_operation = subcontract_row["operation"]

	top_level_item = None
	if subcontracting_order:
		top_level_item = get_top_level_item_for_subcontract_order(subcontracting_order)
	if not top_level_item:
		top_level_item = item_code

	ce_filters = {"item": top_level_item, "docstatus": 1}
	if company:
		ce_filters["company"] = company
	ce_name = frappe.db.get_value(
		"Cost Estimation", ce_filters, "name", order_by="estimation_date desc, creation desc"
	)
	if not ce_name:
		return None

	ce = frappe.get_doc("Cost Estimation", ce_name)

	cumulative = flt(ce.net_rm_cost_per_pc)
	for row in ce.operation_items:
		if row.operation == target_operation:
			break
		cumulative += flt(row.rate_per_pc)

	return {"rate": cumulative, "cost_estimation": ce_name, "operation": target_operation}


@frappe.whitelist()
def get_subcontract_po_rate(fg_item, company=None):
	"""Per-piece service rate to show on a subcontracting Purchase Order row
	for `fg_item` (the finished item coming back from the subcontractor, e.g.
	200632 for Case Hardening, 200633 for Plating) — just that one operation's
	own Rate/Pc, straight off the item's default Subcontract row (Item master
	→ Subcontracting Suppliers), the same rate Cost Estimation itself pulls in.
	Unlike the Stock Entry annexure rate, this is NOT cumulative — a
	subcontracting PO only ever pays for the single operation it's ordering.
	Returns None if fg_item has no subcontract row."""
	row = get_subcontract_operation_row(fg_item, company=company)
	if not row:
		return None
	return {"rate": flt(row["rate_per_pc"]), "operation": row["operation"]}


def _fmt(value):
	return f"₹{flt(value):,.3f}"


def _row(label, value, muted=False, is_total=False):
	classes = "ce-row"
	if muted:
		classes += " ce-row--muted"
	if is_total:
		classes += " ce-row--total"
	return f"""
		<div class="{classes}">
			<span class="ce-row__label">{label}</span>
			<span class="ce-row__value">{_fmt(value)}</span>
		</div>
	"""


def _note_row(text):
	"""A plain explanatory caption line with no ₹ value — for context text
	inside an expanded breakdown (e.g. 'here's how this total was built up')
	that would be misleading rendered as a ₹0.000 cost row via _row()."""
	return f"""
		<div class="ce-row ce-row--muted ce-row--note">
			<span class="ce-row__label">{text}</span>
		</div>
	"""


def _details_row(summary_label, summary_value, child_rows_html, bold=False, item_node=False):
	classes = "ce-row ce-row--parent"
	if bold:
		classes += " ce-row--bold"
	if item_node:
		classes += " ce-row--item-node"
	return f"""
		<details class="ce-node">
			<summary class="{classes}">
				<span class="ce-row__label"><span class="ce-caret">▸</span>{summary_label}</span>
				<span class="ce-row__value">{_fmt(summary_value)}</span>
			</summary>
			<div class="ce-node__children">
				{child_rows_html}
			</div>
		</details>
	"""


CE_SUMMARY_STYLE = """
	<style>
		.ce-summary-tree { width: 100%; font-variant-numeric: tabular-nums; font-size: 14px; }
		.ce-summary-tree .ce-card {
			border: 1px solid var(--border-color); border-radius: var(--border-radius, 8px);
			overflow: hidden; background: var(--fg-color, transparent);
		}
		.ce-summary-tree .ce-row {
			display: flex; align-items: center; justify-content: space-between;
			padding: 11px 20px; gap: 16px; min-width: 0;
		}
		.ce-summary-tree .ce-row__label {
			color: var(--text-color); min-width: 0; overflow: hidden; text-overflow: ellipsis;
			white-space: nowrap; display: flex; align-items: center; flex: 1 1 auto;
		}
		.ce-summary-tree .ce-row__value {
			color: var(--text-color); white-space: nowrap; font-weight: 500; flex: 0 0 auto;
		}
		.ce-summary-tree .ce-row--muted .ce-row__label,
		.ce-summary-tree .ce-row--muted .ce-row__value { color: var(--text-muted); font-weight: 400; }
		.ce-summary-tree .ce-row--bold .ce-row__label,
		.ce-summary-tree .ce-row--bold .ce-row__value { font-weight: 600; }
		/* Plain caption line inside a breakdown (no ₹ value) — the
		   explanatory sentence is longer than a normal row label, so let it
		   wrap onto multiple lines instead of being ellipsis-truncated. */
		.ce-summary-tree .ce-row--note .ce-row__label {
			white-space: normal; font-style: italic; font-size: 12.5px; line-height: 1.4;
		}
		.ce-summary-tree .ce-row--total {
			background: var(--control-bg); font-weight: 600;
			border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color);
		}
		.ce-summary-tree .ce-row--total .ce-row__label,
		.ce-summary-tree .ce-row--total .ce-row__value { font-weight: 600; }
		.ce-summary-tree .ce-node:not(:last-child) { border-bottom: 1px solid var(--border-color); }
		.ce-summary-tree .ce-row--parent { cursor: pointer; list-style: none; }
		.ce-summary-tree .ce-row--parent::-webkit-details-marker { display: none; }
		.ce-summary-tree .ce-row--parent:hover { background: var(--control-bg); }
		/* Item/group nodes (a rollup of everything nested inside them) get an
		   accent color + bold weight so they read as a subtotal at a glance,
		   distinct from a plain (muted) single-operation cost line. */
		.ce-summary-tree .ce-row--item-node .ce-row__label,
		.ce-summary-tree .ce-row--item-node .ce-row__value {
			color: var(--blue-600, #2490ef); font-weight: 600;
		}
		.ce-summary-tree .ce-caret {
			display: inline-block; width: 14px; flex-shrink: 0; margin-right: 8px;
			color: var(--text-muted); font-size: 10px; transition: transform 0.15s ease;
		}
		.ce-summary-tree details[open] > summary .ce-caret { transform: rotate(90deg); }
		/* Each nesting level narrows the row (margin-right grows with depth
		   too, not just margin-left) so a row's ₹ value sits close to its own
		   label at that depth, instead of every row's value lining up flush
		   against the outermost card edge regardless of how deep it is. */
		.ce-summary-tree .ce-node__children {
			margin: 0 14px 10px 26px; padding-left: 14px;
			border-left: 2px solid var(--border-color);
		}
		.ce-summary-tree .ce-node__children .ce-row { padding: 7px 10px; }
		.ce-summary-tree .ce-hero {
			margin-top: 16px; padding: 18px 24px; border-radius: var(--border-radius, 8px);
			background: var(--control-bg); border: 1px solid var(--border-color);
			display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px;
		}
		.ce-summary-tree .ce-hero__label {
			font-size: 12.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em;
		}
		.ce-summary-tree .ce-hero__value {
			font-size: 28px; font-weight: 700; color: var(--text-color);
		}
	</style>
"""


def _operation_leaf_row(r):
	qty_multiplier = flt(r.qty_multiplier)
	label = (
		f"{r.operation or '—'} — {r.machine_name or r.workstation or 'no machine'}  "
		f"({flt(r.shift_rate_per_min):.3f} ÷ {flt(r.time_per_pc_min):.3f} pc/min"
		f"{f' ÷ {flt(r.no_of_cavities):.0f} cav' if flt(r.no_of_cavities) else ''}"
		f"{f' × {qty_multiplier:.3f} qty' if qty_multiplier and qty_multiplier != 1 else ''})"
	)

	if not r.assembly_breakdown_json:
		return _row(label, r.rate_per_pc, muted=True)

	# Single Assembly row costing several sub-parts — expand into the
	# per-sub-part contributions so it's clear how the one row's Rate/Pc
	# was built up, without turning it into several grid rows (the physical
	# action is still one Assembly step, done once). The label itself flags
	# "N components" so it's visibly different from a plain operation row
	# BEFORE it's expanded, not just once opened — otherwise there's nothing
	# to suggest clicking it reveals anything more than the usual one-line
	# cost, since the collapsed row looks identical to a normal operation.
	base_rate = compute_rate_per_pc(r.shift_rate_per_min, r.time_per_pc_min, r.no_of_cavities)
	breakdown = frappe.parse_json(r.assembly_breakdown_json)
	total_qty = sum(flt(entry.get("qty_multiplier")) for entry in breakdown)

	label_with_hint = (
		f"{label}  — {len(breakdown)} components, {total_qty:.0f} pcs assembled per unit "
		f"(click to see per-part cost)"
	)

	explainer_row = _note_row(
		f"One Assembly step, done once — its Rate/Pc ({_fmt(r.rate_per_pc)}) is this operation's "
		f"per-piece rate ({flt(base_rate):.3f}/pc) × how many of each part go into one finished unit, summed:"
	)

	def _breakdown_entry_row(entry):
		item = entry.get("item") or "—"
		item_name = entry.get("item_name")
		name_part = f" — {item_name}" if item_name and item_name != entry.get("item") else ""
		qty = flt(entry.get("qty_multiplier"))
		return _row(
			f"{item}{name_part}: {qty:.0f} pcs × {flt(base_rate):.3f}/pc",
			base_rate * qty,
			muted=True,
		)

	breakdown_rows = explainer_row + "".join(_breakdown_entry_row(entry) for entry in breakdown)
	return _details_row(label_with_hint, r.rate_per_pc, breakdown_rows)


def build_operation_tree_html(operation_items, item_tree_edges=None):
	"""Renders Operations as a nested BOM tree — one expandable node per item,
	holding that item's own operation rows plus (nested inside) the node of
	every item its BOM consumes, mirroring explode_bom_tree's walk. Rows
	with no `item` tagged (e.g. typed in by hand, not pulled from a BOM) are
	shown as a flat, untitled group so manual entries aren't silently
	dropped.

	`item_tree_edges` — (item, parent_item) pairs for EVERY item the BOM walk
	visited, from explode_bom_tree/CostEstimation.item_tree_json — is the
	source of truth for parent linkage, since a pure-container assembly (one
	with sub-items that have operations but none of its own) never appears
	as an `item` on any operation row and so can't otherwise be placed in
	the tree correctly. Falls back to each row's own `parent_item` for any
	item missing from the edges (e.g. older records saved before this field
	existed, or hand-typed rows)."""
	untagged = [r for r in operation_items if not r.item]
	tagged = [r for r in operation_items if r.item]

	if not tagged and not untagged:
		return _row("No operation rows", 0, muted=True)

	item_parent = {}
	for item, parent in item_tree_edges or []:
		if item and item not in item_parent:
			item_parent[item] = parent

	rows_by_item = {}
	item_order = []
	for r in tagged:
		if r.item not in rows_by_item:
			rows_by_item[r.item] = []
			item_order.append(r.item)
		rows_by_item[r.item].append(r)
		if r.item not in item_parent:
			item_parent[r.item] = r.parent_item

	# A pure-container assembly (sub-items have operations, it has none of
	# its own) is known only from item_tree_edges, never from a row's own
	# `item` — add it to item_order so it gets a node in the tree instead of
	# its children being orphaned to root.
	for item in list(item_parent):
		if item not in rows_by_item:
			rows_by_item[item] = []
			item_order.append(item)

	children_by_parent = {}
	for item in item_order:
		children_by_parent.setdefault(item_parent.get(item) or None, []).append(item)

	# Root items are ones with no parent_item, or whose parent_item is
	# nowhere in this tree (e.g. a subcontract-only estimate) — treat both
	# as top of the tree so nothing silently disappears.
	known_items = set(item_order)
	roots = [
		item
		for item in item_order
		if not item_parent.get(item) or item_parent[item] not in known_items
	]
	# Preserve walk order and avoid duplicates if the same item appears twice.
	seen = set()
	roots = [i for i in roots if not (i in seen or seen.add(i))]

	item_names = {
		d.name: d.item_name
		for d in frappe.get_all("Item", filters={"name": ["in", item_order]}, fields=["name", "item_name"])
	}

	def item_label(item):
		name = item_names.get(item)
		return f"{item} — {name}" if name and name != item else item

	def item_subtotal(item, visited):
		if item in visited:
			return 0.0
		visited.add(item)
		total = sum(flt(r.rate_per_pc) for r in rows_by_item.get(item, []))
		for child in children_by_parent.get(item, []):
			total += item_subtotal(child, visited)
		return total

	# A pure-RM item (e.g. a raw sheet/strip consumed further down the tree,
	# with no operation performed on it and no sub-items of its own with
	# operations) contributes nothing to labour cost and would only be an
	# empty, always-zero node here — RM cost is already shown in its own
	# section above, so prune these rather than duplicate/clutter. An
	# assembly (SFG/FG) with operation-bearing children is always kept, even
	# when it has no operation of its own — only truly empty branches drop.
	def has_operations(item, visited):
		if item in visited:
			return False
		visited.add(item)
		if rows_by_item.get(item):
			return True
		return any(has_operations(child, set(visited)) for child in children_by_parent.get(item, []))

	def render_item_node(item, visited):
		if item in visited or not has_operations(item, set()):
			return ""
		visited.add(item)
		own_rows = "".join(_operation_leaf_row(r) for r in rows_by_item.get(item, []))
		child_nodes = "".join(
			render_item_node(child, visited) for child in children_by_parent.get(item, [])
		)
		return _details_row(item_label(item), item_subtotal(item, set()), own_rows + child_nodes, item_node=True)

	visited = set()
	tree_html = "".join(render_item_node(item, visited) for item in roots)

	untagged_html = ""
	if untagged:
		untagged_html = "".join(_operation_leaf_row(r) for r in untagged)

	return tree_html + untagged_html


def build_summary_tree_html(doc):
	"""Nested, expandable (<details>/<summary>) breakdown of every cost line
	on the estimate — click a subtotal (Gross RM Cost, Operations Cost, etc.)
	to see exactly which item/operation rows it's made of and at what
	rate/qty, without cluttering the collapsed view."""
	def _rm_scrap_label(item_code, item_name, bom, wt, rate):
		name_part = f" — {item_name}" if item_name and item_name != item_code else ""
		bom_part = f"  [{bom}]" if bom else ""
		return f"{item_code or '—'}{name_part}{bom_part}  ({flt(wt):.3f} kg × {flt(rate):.3f})"

	rm_child_rows = "".join(
		_row(
			_rm_scrap_label(r.rm_used, r.item_name, r.bom, r.gross_wt_per_pc, r.rm_rate_per_kg),
			r.gross_rm_cost_per_pc,
			muted=True,
		)
		for r in doc.rm_items
	) or _row("No RM rows", 0, muted=True)

	scrap_child_rows = "".join(
		_row(
			_rm_scrap_label(r.scrap_description, r.item_name, r.bom, r.scrap_wt_per_pc, r.scrap_rate_per_kg),
			r.scrap_price_per_pc,
			muted=True,
		)
		for r in doc.scrap_items
	) or _row("No scrap rows", 0, muted=True)

	item_tree_edges = frappe.parse_json(doc.item_tree_json) if doc.item_tree_json else []
	op_child_rows = build_operation_tree_html(doc.operation_items, item_tree_edges)

	other_cost_rows = "".join(
		[
			_row(
				f"Inventory Carrying ({flt(doc.inventory_carrying_pct):.2f}%)",
				doc.inventory_carrying_cost,
				muted=True,
			),
			_row(
				f"Packing & Forwarding ({flt(doc.packing_forwarding_pct):.2f}%)",
				doc.packing_forwarding_cost,
				muted=True,
			),
			_row(f"Rejection ({flt(doc.rejection_pct):.2f}%)", doc.rejection_cost, muted=True),
		]
	)
	other_costs_total = (
		flt(doc.inventory_carrying_cost) + flt(doc.packing_forwarding_cost) + flt(doc.rejection_cost)
	)

	body = "".join(
		[
			_details_row("Gross RM Cost / Pc", doc.total_gross_rm_cost_per_pc, rm_child_rows),
			_details_row("Scrap Recovery / Pc", -flt(doc.total_scrap_price_per_pc), scrap_child_rows),
			_row("Net RM Cost / Pc", doc.net_rm_cost_per_pc, is_total=True),
			_details_row(
				"Total Labour (Operations) Cost / Pc",
				doc.total_labour_cost_per_pc,
				op_child_rows,
				bold=True,
			),
			_details_row("Other Costs / Pc", other_costs_total, other_cost_rows, bold=True),
			_row("Total Cost / Pc", doc.total_cost_per_pc, is_total=True),
			_row(
				"Profit Amount / Pc"
				+ (f" ({flt(doc.profit_pct):.2f}%)" if doc.profit_mode == "Percentage" else " (flat)"),
				doc.profit_amount,
				muted=True,
			),
			_row("Total Component Cost / Pc", doc.total_component_cost, is_total=True),
		]
	)

	return f"""
		{CE_SUMMARY_STYLE}
		<div class="ce-summary-tree">
			<div class="ce-card">
				{body}
			</div>
			<div class="ce-hero">
				<div class="ce-hero__label">Total Component Cost &times; Qty ({flt(doc.qty):.3f})</div>
				<div class="ce-hero__value">{_fmt(doc.total_component_cost_for_qty)}</div>
			</div>
		</div>
	"""


class CostEstimation(Document):
	def validate(self):
		# Re-explode the BOM tree when the BOM field doesn't match what it was
		# last pulled from (user picked a different BOM), OR when Quantity has
		# changed since the last pull (RM/Scrap weights scale with Quantity,
		# see explode_bom_tree's qty_multiplier). A brand-new record whose
		# tables were already populated by the live client-side fetch has
		# last_pulled_bom/last_pulled_qty set to match, so this correctly does
		# nothing and preserves any edits made since. This is what replaces
		# the old "Pull from BOM" button.
		if self.bom and (self.bom != self.last_pulled_bom or flt(self.qty) != flt(self.last_pulled_qty)):
			self.apply_bom_explosion()

		self.calculate_rm_cost()
		self.calculate_operations_cost()
		self.calculate_other_costs()
		self.calculate_totals()
		self.set_summary_html()

	def apply_bom_explosion(self):
		data = explode_bom_tree(
			self.bom, per_pc_qty=1, company=self.company, estimate_qty=flt(self.qty) or 1
		)
		if self.item:
			trailing = get_subcontract_operation_row(self.item, company=self.company)
			if trailing:
				trailing["item"] = self.item
				trailing["parent_item"] = None
				data["operation_items"].append(trailing)

		self.rm_items = []
		for row in data["rm_items"]:
			self.append("rm_items", row)

		self.scrap_items = []
		for row in data["scrap_items"]:
			self.append("scrap_items", row)

		self.operation_items = []
		for row in data["operation_items"]:
			self.append("operation_items", row)

		self.last_pulled_bom = self.bom
		self.last_pulled_qty = flt(self.qty) or 1
		self.item_tree_json = frappe.as_json(data["item_tree_edges"])

	def calculate_rm_cost(self):
		total_gross_rm_cost = 0.0
		for row in self.rm_items:
			row.gross_rm_cost_per_pc = flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg)
			total_gross_rm_cost += flt(row.gross_rm_cost_per_pc)
		self.total_gross_rm_cost_per_pc = total_gross_rm_cost

		total_scrap_price = 0.0
		for row in self.scrap_items:
			row.scrap_price_per_pc = flt(row.scrap_wt_per_pc) * flt(row.scrap_rate_per_kg)
			total_scrap_price += flt(row.scrap_price_per_pc)
		self.total_scrap_price_per_pc = total_scrap_price

		self.net_rm_cost_per_pc = self.total_gross_rm_cost_per_pc - self.total_scrap_price_per_pc

	def calculate_operations_cost(self):
		total_labour_cost = 0.0
		for row in self.operation_items:
			if row.workstation:
				if not row.shift_rate_per_min:
					row.shift_rate_per_min = frappe.db.get_value(
						"Workstation", row.workstation, "custom_cost_per_min"
					)
				if not row.machine_name:
					asset = frappe.db.get_value("Workstation", row.workstation, "custom_asset_name")
					row.machine_name = frappe.db.get_value("Asset", asset, "asset_name") if asset else None

				# Rate per Pc is always user-editable. Only auto-compute it here
				# when it's still empty (a fresh/BOM-pulled row) — once a value
				# is present, whether typed by hand or from an earlier
				# calculation, later saves leave it alone so a manual override
				# survives.
				if not row.rate_per_pc and flt(row.time_per_pc_min):
					if row.assembly_breakdown_json:
						row.rate_per_pc = compute_assembly_breakdown_rate(
							row.shift_rate_per_min,
							row.time_per_pc_min,
							row.no_of_cavities,
							frappe.parse_json(row.assembly_breakdown_json),
						)
					else:
						row.rate_per_pc = compute_rate_per_pc(
							row.shift_rate_per_min, row.time_per_pc_min, row.no_of_cavities, row.qty_multiplier
						)
			# else: no machine (e.g. subcontracted Plating) — rate_per_pc is typed directly, left as-is

			total_labour_cost += flt(row.rate_per_pc)

		self.total_labour_cost_per_pc = total_labour_cost

	def _base_for_pct(self):
		# net_rm_cost_per_pc already carries the Quantity scaling (RM/Scrap
		# weights are exploded with qty_multiplier = Quantity), but
		# total_labour_cost_per_pc is intentionally still a true per-single-
		# piece figure (Operations' cycle time/rate don't scale with how many
		# pieces are quoted) — so it's multiplied by Quantity here, once, to
		# bring it onto the same "for this Quantity" basis as RM/Scrap before
		# the two are combined. Everything downstream of this (other costs,
		# profit, totals) is therefore already on the "for Quantity" basis.
		return flt(self.net_rm_cost_per_pc) + flt(self.total_labour_cost_per_pc) * (flt(self.qty) or 1)

	def calculate_other_costs(self):
		base_for_pct = self._base_for_pct()

		rm_value_for_inventory = sum(
			flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg) for row in self.rm_items
		)
		self.inventory_carrying_cost = rm_value_for_inventory * flt(self.inventory_carrying_pct) / 100
		self.packing_forwarding_cost = base_for_pct * flt(self.packing_forwarding_pct) / 100
		self.rejection_cost = base_for_pct * flt(self.rejection_pct) / 100

	def calculate_totals(self):
		base_for_pct = self._base_for_pct()

		self.total_cost_per_pc = (
			base_for_pct
			+ flt(self.inventory_carrying_cost)
			+ flt(self.packing_forwarding_cost)
			+ flt(self.rejection_cost)
		)

		if self.profit_mode == "Percentage":
			self.profit_amount = base_for_pct * flt(self.profit_pct) / 100

		self.total_component_cost = flt(self.total_cost_per_pc) + flt(self.profit_amount)
		# total_cost_per_pc/total_component_cost are already computed on the
		# "for this Quantity" basis via _base_for_pct() above, so the final
		# total is NOT multiplied by Quantity again here (unlike before this
		# field was named "for_qty" to describe a second multiply).
		self.total_component_cost_for_qty = self.total_component_cost

	def set_summary_html(self):
		self.summary_html = build_summary_tree_html(self)
