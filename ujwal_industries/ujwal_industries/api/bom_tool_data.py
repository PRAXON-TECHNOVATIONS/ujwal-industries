import re

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

# Ordered longest/most-specific keyword first, matched against the tool name's
# last "\"-separated segment to infer an Operation when Tool Child Table leaves it blank.
TOOL_KEYWORD_TO_OPERATION = [
	(r"1st\s*bend.*piearc", "1st Bend Piearcing"),
	(r"2nd\s*bend.*piearc", "2nd Bend Piearcing"),
	(r"1st\s*bend", "1st Bending"),
	(r"2nd\s*bend", "2nd Bending"),
	(r"3rd\s*bend", "3rd Bending"),
	(r"v\s*bend", "V Bending"),
	(r"l\s*bend", "L Bending"),
	(r"bend", "Bending"),
	(r"piearc|pierc", "Piercing"),
	(r"blank", "Blanking"),
	(r"sizing", "Sizing"),
	(r"chamfer", "Chamfering"),
	(r"shave", "Shaving"),
	(r"twist", "Twisting"),
	(r"rivet", "Rivetting"),
	(r"forg", "Forging"),
	(r"ring\s*cut", "Ring Cutting"),
	(r"side\s*cut", "Side cutting"),
	(r"flat", "Flaterning"),
	(r"deburr", "Deburring"),
	(r"drill", "Drilling"),
	(r"grind", "Grinding"),
	(r"weld", "Welding"),
	(r"crimp", "Crimping"),
	(r"punch", "Punching"),
	(r"notch", "Notching"),
	(r"mill", "Milling"),
	(r"turn", "Turning"),
	(r"plat", "Plating"),
]


def infer_operation_from_tool(tool_name):
	if not tool_name:
		return None

	segment = tool_name.split("\\")[-1].strip()

	for pattern, operation in TOOL_KEYWORD_TO_OPERATION:
		if re.search(pattern, segment, re.IGNORECASE):
			return operation

	return None


def get_default_bom_for_item(item_code):
	return frappe.db.get_value("BOM", {"item": item_code, "is_default": 1, "docstatus": 1}, "name")


def get_all_boms_in_tree(fg_bom_name):
	"""Walk the BOM explosion (FG -> sub-assembly BOMs -> ...) and return every
	BOM name reachable from the FG's default BOM, so tools defined on nested
	raw-material/sub-assembly BOMs are picked up under the FG as well."""
	seen = set()
	queue = [fg_bom_name]

	while queue:
		bom_name = queue.pop()
		if bom_name in seen:
			continue
		seen.add(bom_name)

		sub_items = frappe.get_all(
			"BOM Item",
			filters={"parent": bom_name, "bom_no": ["is", "set"]},
			fields=["bom_no"],
		)
		for row in sub_items:
			if row.bom_no and row.bom_no not in seen:
				queue.append(row.bom_no)

		# some sub-assembly rows only carry item_code without an explicit bom_no;
		# resolve those via the item's own default BOM
		sub_items_without_bom = frappe.get_all(
			"BOM Item",
			filters={"parent": bom_name, "bom_no": ["in", ["", None]]},
			fields=["item_code"],
		)
		for row in sub_items_without_bom:
			sub_bom = get_default_bom_for_item(row.item_code)
			if sub_bom and sub_bom not in seen:
				queue.append(sub_bom)

	return list(seen)


def get_status(tool, matching_jcs, maintenance_assets):
	if tool in maintenance_assets:
		return "Under Maintenance"

	if matching_jcs:
		latest_jc = max(matching_jcs, key=lambda jc: jc.modified)
		if latest_jc.status == "Completed":
			return "Production Completed"

	return "Ready for Production"


def get_bom_tool_rows(filters=None):
	"""Return one flattened row per FG + Operation + Tool combination, covering
	every tool anywhere in the FG's nested BOM tree (sub-assemblies included).

	Each row: fg_part_no, item_name, operation, tool, qty_produced, status.
	"""
	filters = filters or {}
	item_filter = filters.get("item")
	tool_filter = filters.get("tool")
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	fg_conditions = ["tb.is_default = 1", "tb.docstatus = 1", "tb.item LIKE '300%%'"]
	fg_params = {}
	if item_filter:
		fg_conditions.append("tb.item = %(item)s")
		fg_params["item"] = item_filter

	fg_boms = frappe.db.sql(
		f"""
		SELECT tb.name AS bom_name, tb.item AS fg_part_no, tb.item_name AS item_name, it.custom_part_number AS part_no
		FROM `tabBOM` tb
		LEFT JOIN `tabItem` it ON it.name = tb.item
		WHERE {' AND '.join(fg_conditions)}
		ORDER BY tb.item
		""",
		fg_params,
		as_dict=True,
	)

	if not fg_boms:
		return []

	# expand each FG's BOM into every nested sub-assembly BOM it references
	fg_bom_scope = {}
	all_bom_names = set()
	for fg in fg_boms:
		nested_boms = get_all_boms_in_tree(fg.bom_name)
		fg_bom_scope[fg.bom_name] = nested_boms
		all_bom_names.update(nested_boms)

	tool_records_raw = (
		frappe.get_all(
			"Tool Child Table",
			filters={"parent": ["in", list(all_bom_names)]},
			fields=["parent AS bom_name", "operation", "tool", "tool_load_quantity"],
		)
		if all_bom_names
		else []
	)

	tools_by_bom = {}
	for row in tool_records_raw:
		tools_by_bom.setdefault(row.bom_name, []).append(row)

	# flatten: every tool found anywhere in the FG's nested BOM tree is attributed
	# to that FG directly (FG > Operation > Tool)
	tool_records = []
	for fg in fg_boms:
		for nested_bom_name in fg_bom_scope[fg.bom_name]:
			for tool_row in tools_by_bom.get(nested_bom_name, []):
				tool_records.append(
					frappe._dict(
						bom_name=fg.bom_name,
						fg_part_no=fg.fg_part_no,
						item_name=fg.item_name,
						part_no=fg.part_no,
						operation=tool_row.operation,
						tool=tool_row.tool,
						tool_load_quantity=tool_row.tool_load_quantity,
						source_bom=nested_bom_name,
					)
				)

	if tool_filter:
		tool_records = [r for r in tool_records if r.tool == tool_filter]

	if not tool_records:
		return []

	# Job Cards are raised against whichever BOM actually carries the operation
	# (the FG's own BOM or a nested sub-assembly BOM), so match against source_bom.
	bom_names = list({r.source_bom for r in tool_records})
	today = nowdate()

	jc_filters = {
		"bom_no": ["in", bom_names],
		"docstatus": ["!=", 2],
	}
	if from_date and to_date:
		jc_filters["expected_start_date"] = ["between", [from_date, to_date]]

	job_cards = frappe.get_all(
		"Job Card",
		filters=jc_filters,
		fields=[
			"bom_no",
			"operation",
			"custom_tool_name",
			"total_completed_qty",
			"status",
			"modified",
		],
	)

	# group job cards by (bom_no, operation, tool) so we can sum qty and find the latest one
	jc_map = {}
	for jc in job_cards:
		if not jc.custom_tool_name:
			continue
		key = (jc.bom_no, jc.operation, jc.custom_tool_name)
		jc_map.setdefault(key, []).append(jc)

	# Tools with an open (not completed, not cancelled) maintenance task that has
	# already started, keyed by asset name. end_date is often left blank until the
	# task is actually closed out, so completion must be judged from
	# last_completion_date / maintenance_status rather than the date range.
	assets_in_scope = list({r.tool for r in tool_records if r.tool})
	maintenance_assets = set()
	if assets_in_scope:
		rows = frappe.db.sql(
			"""
			SELECT DISTINCT am.asset_name
			FROM `tabAsset Maintenance` am
			INNER JOIN `tabAsset Maintenance Task` mt ON mt.parent = am.name
			WHERE am.asset_name IN %(assets)s
				AND mt.maintenance_status != 'Cancelled'
				AND mt.last_completion_date IS NULL
				AND mt.start_date <= %(today)s
			""",
			{"assets": assets_in_scope, "today": today},
			as_dict=True,
		)
		maintenance_assets = {r.asset_name for r in rows}

	# flatten to one row per FG + Operation + Tool, inferring the operation from
	# the tool name when Tool Child Table leaves it blank
	rows = []
	for tool_row in tool_records:
		tool = tool_row.tool
		if not tool:
			continue

		operation = tool_row.operation or infer_operation_from_tool(tool) or _("Unspecified")
		key = (tool_row.source_bom, operation, tool)
		matching_jcs = jc_map.get(key, [])

		qty_produced = sum(jc.total_completed_qty or 0 for jc in matching_jcs)
		status = get_status(tool, matching_jcs, maintenance_assets)

		rows.append(
			{
				"fg_part_no": tool_row.fg_part_no,
				"item_name": tool_row.item_name,
				"part_no": tool_row.part_no,
				"operation": operation,
				"tool": tool,
				"qty_produced": qty_produced,
				"status": status,
			}
		)

	return rows


def get_tool_readiness_rows(filters=None):
	"""Return one row per FG + Tool combination with the earliest upcoming
	Production Plan schedule date for the BOM level that tool actually sits on,
	plus its current readiness status, so the tool team knows what must be
	ready and by when.

	Each row: fg_part_no, item_name, part_no, tool, pp_start_date,
	remaining_days, status.
	"""
	filters = filters or {}
	item_filter = filters.get("item")

	fg_conditions = ["tb.is_default = 1", "tb.docstatus = 1", "tb.item LIKE '300%%'"]
	fg_params = {}
	if item_filter:
		fg_conditions.append("tb.item = %(item)s")
		fg_params["item"] = item_filter

	fg_boms = frappe.db.sql(
		f"""
		SELECT tb.name AS bom_name, tb.item AS fg_part_no, tb.item_name AS item_name, it.custom_part_number AS part_no
		FROM `tabBOM` tb
		LEFT JOIN `tabItem` it ON it.name = tb.item
		WHERE {' AND '.join(fg_conditions)}
		ORDER BY tb.item
		""",
		fg_params,
		as_dict=True,
	)

	if not fg_boms:
		return []

	# expand each FG's BOM into every nested sub-assembly BOM it references
	fg_bom_scope = {}
	all_bom_names = set()
	for fg in fg_boms:
		nested_boms = get_all_boms_in_tree(fg.bom_name)
		fg_bom_scope[fg.bom_name] = nested_boms
		all_bom_names.update(nested_boms)

	tool_records_raw = (
		frappe.get_all(
			"Tool Child Table",
			filters={"parent": ["in", list(all_bom_names)]},
			fields=["parent AS bom_name", "operation", "tool", "tool_load_quantity"],
		)
		if all_bom_names
		else []
	)

	tools_by_bom = {}
	for row in tool_records_raw:
		tools_by_bom.setdefault(row.bom_name, []).append(row)

	# flatten: every tool anywhere in the FG's nested BOM tree, tagged with the
	# specific BOM it belongs to (source_bom) so it can be matched to that
	# BOM level's own Production Plan schedule date, not the FG's.
	tool_records = []
	for fg in fg_boms:
		for nested_bom_name in fg_bom_scope[fg.bom_name]:
			for tool_row in tools_by_bom.get(nested_bom_name, []):
				if not tool_row.tool:
					continue
				tool_records.append(
					frappe._dict(
						fg_part_no=fg.fg_part_no,
						item_name=fg.item_name,
						part_no=fg.part_no,
						tool=tool_row.tool,
						source_bom=nested_bom_name,
					)
				)

	if not tool_records:
		return []

	bom_names = list({r.source_bom for r in tool_records})
	schedule_by_bom = _get_earliest_upcoming_schedule_by_bom(bom_names)

	assets_in_scope = list({r.tool for r in tool_records})
	maintenance_assets = _get_maintenance_assets(assets_in_scope)
	jc_map = _get_job_card_map(bom_names)

	today = getdate(nowdate())
	rows = []
	for tool_row in tool_records:
		pp_start_date = schedule_by_bom.get(tool_row.source_bom)
		if not pp_start_date:
			# no genuinely upcoming Production Plan need for this tool right now
			continue

		remaining_days = (getdate(pp_start_date) - today).days

		matching_jcs = [
			jc for jc in jc_map.get(tool_row.source_bom, []) if jc.custom_tool_name == tool_row.tool
		]
		status = get_status(tool_row.tool, matching_jcs, maintenance_assets)

		rows.append(
			{
				"fg_part_no": tool_row.fg_part_no,
				"item_name": tool_row.item_name,
				"part_no": tool_row.part_no,
				"tool": tool_row.tool,
				"pp_start_date": pp_start_date,
				"remaining_days": remaining_days,
				"status": status,
			}
		)

	return rows


def _get_earliest_upcoming_schedule_by_bom(bom_names):
	"""For each BOM, the earliest schedule_date (today or later) across every
	open Production Plan that references it, from either the FG-level
	Production Plan Item or the exploded Production Plan Sub Assembly Item.

	A BOM with only past-dated schedule entries (no genuinely upcoming need)
	is left out of the result entirely, rather than surfacing a stale date.
	"""
	if not bom_names:
		return {}

	open_pp_statuses = ["Completed", "Closed", "Cancelled"]

	pp_item_rows = frappe.db.sql(
		"""
		SELECT ppi.bom_no, ppi.planned_start_date AS schedule_date
		FROM `tabProduction Plan Item` ppi
		INNER JOIN `tabProduction Plan` pp ON pp.name = ppi.parent
		WHERE ppi.bom_no IN %(boms)s
			AND pp.docstatus = 1
			AND pp.status NOT IN %(closed_statuses)s
			AND ppi.planned_start_date IS NOT NULL
		""",
		{"boms": bom_names, "closed_statuses": open_pp_statuses},
		as_dict=True,
	)

	sub_assembly_rows = frappe.db.sql(
		"""
		SELECT psa.bom_no, psa.schedule_date AS schedule_date
		FROM `tabProduction Plan Sub Assembly Item` psa
		INNER JOIN `tabProduction Plan` pp ON pp.name = psa.parent
		WHERE psa.bom_no IN %(boms)s
			AND pp.docstatus = 1
			AND pp.status NOT IN %(closed_statuses)s
			AND psa.schedule_date IS NOT NULL
		""",
		{"boms": bom_names, "closed_statuses": open_pp_statuses},
		as_dict=True,
	)

	today = getdate(nowdate())
	earliest_upcoming = {}

	for row in pp_item_rows + sub_assembly_rows:
		d = getdate(row.schedule_date)
		if d < today:
			continue

		if row.bom_no not in earliest_upcoming or d < earliest_upcoming[row.bom_no]:
			earliest_upcoming[row.bom_no] = d

	return earliest_upcoming


def _get_maintenance_assets(assets_in_scope):
	if not assets_in_scope:
		return set()

	today = nowdate()
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT am.asset_name
		FROM `tabAsset Maintenance` am
		INNER JOIN `tabAsset Maintenance Task` mt ON mt.parent = am.name
		WHERE am.asset_name IN %(assets)s
			AND mt.maintenance_status != 'Cancelled'
			AND mt.last_completion_date IS NULL
			AND mt.start_date <= %(today)s
		""",
		{"assets": assets_in_scope, "today": today},
		as_dict=True,
	)
	return {r.asset_name for r in rows}


def _get_job_card_map(bom_names):
	if not bom_names:
		return {}

	job_cards = frappe.get_all(
		"Job Card",
		filters={"bom_no": ["in", bom_names], "docstatus": ["!=", 2]},
		fields=["bom_no", "operation", "custom_tool_name", "total_completed_qty", "status", "modified"],
	)

	by_bom = {}
	for jc in job_cards:
		if not jc.custom_tool_name:
			continue
		by_bom.setdefault(jc.bom_no, []).append(jc)
	return by_bom
