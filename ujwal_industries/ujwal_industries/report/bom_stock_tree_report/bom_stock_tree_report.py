import json

import frappe
from frappe import _, scrub
from frappe.utils import cint, flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.warehouses = parse_multi_select(filters.get("warehouses"))
	filters.max_depth = cint(filters.get("max_depth") or 10)

	selected_warehouses = get_selected_warehouses(filters)
	filters.resolved_warehouse_names = get_resolved_warehouse_names(selected_warehouses)
	boms = get_boms(filters)

	if not boms:
		return get_columns([]), []

	item_codes = set()
	bom_cache = {}
	for bom in boms:
		collect_item_codes(bom.name, item_codes, bom_cache, filters.max_depth)
		item_codes.add(bom.item)

	total_stock_map = get_total_stock_map(item_codes, filters)
	breakup_stock_map = get_breakup_stock_map(item_codes, filters)
	if not selected_warehouses:
		selected_warehouses = get_breakup_based_warehouses(breakup_stock_map)
	warehouse_stock_map = get_warehouse_stock_map(item_codes, selected_warehouses, breakup_stock_map)
	columns = get_columns(selected_warehouses)
	data = build_tree_data(
		boms,
		total_stock_map,
		breakup_stock_map,
		warehouse_stock_map,
		selected_warehouses,
		bom_cache,
		filters.max_depth,
	)

	return columns, data


def get_columns(warehouses):
	columns = [
		{
			"fieldname": "bom_no",
			"label": _("BOM"),
			"fieldtype": "Link",
			"options": "BOM",
			"width": 180,
		},
		{
			"fieldname": "item_code",
			"label": _("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 180,
		},
		{
			"fieldname": "item_name",
			"label": _("Item Name"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "row_type",
			"label": _("Row Type"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "total_actual_stock",
			"label": _("Total Actual Stock"),
			"fieldtype": "Float",
			"width": 140,
		},
		{
			"fieldname": "warehouse_breakup",
			"label": _("Warehouse Qty Breakup"),
			"fieldtype": "Data",
			"width": 320,
		},
		{
			"fieldname": "stock_uom",
			"label": _("UOM"),
			"fieldtype": "Link",
			"options": "UOM",
			"width": 90,
		},
	]

	for warehouse in warehouses:
		columns.append(
			{
				"fieldname": warehouse.fieldname,
				"label": warehouse.label,
				"fieldtype": "Float",
				"width": 130,
			}
		)

	return columns


def get_boms(filters):
	bom_filters = {"docstatus": 1, "is_active": 1}

	if filters.get("company"):
		bom_filters["company"] = filters.company

	if filters.get("bom"):
		bom_filters["name"] = filters.bom

	if filters.get("item"):
		bom_filters["item"] = filters.item

	return frappe.get_all(
		"BOM",
		filters=bom_filters,
		fields=["name", "item", "item_name", "quantity", "uom", "company"],
		order_by="item asc, name asc",
	)


def get_selected_warehouses(filters):
	selected_warehouses = filters.get("warehouses") or []
	if not selected_warehouses:
		return []

	warehouse_filters = {
		"disabled": 0,
		"name": ["in", selected_warehouses],
	}

	if filters.get("company"):
		warehouse_filters["company"] = filters.company

	warehouses = frappe.get_all(
		"Warehouse",
		filters=warehouse_filters,
		fields=["name", "is_group", "lft", "rgt"],
	)

	warehouse_map = {warehouse.name: warehouse for warehouse in warehouses}
	ordered_warehouses = []
	seen_leaf_warehouses = set()

	for warehouse_name in selected_warehouses:
		warehouse = warehouse_map.get(warehouse_name)
		if not warehouse:
			continue

		child_warehouses = get_child_warehouses(warehouse, filters.get("company"))
		for child_warehouse in child_warehouses:
			if child_warehouse in seen_leaf_warehouses:
				continue

			seen_leaf_warehouses.add(child_warehouse)
			ordered_warehouses.append(
				frappe._dict(
					{
						"name": child_warehouse,
						"is_group": 0,
						"fieldname": f"warehouse_{scrub(child_warehouse)}",
						"label": child_warehouse,
						"child_warehouses": [child_warehouse],
					}
				)
			)

	return ordered_warehouses


def get_child_warehouses(warehouse, company=None):
	if not cint(warehouse.is_group):
		return [warehouse.name]

	filters = {
		"lft": [">", warehouse.lft],
		"rgt": ["<", warehouse.rgt],
		"is_group": 0,
		"disabled": 0,
	}
	if company:
		filters["company"] = company

	return frappe.get_all("Warehouse", filters=filters, pluck="name", order_by="lft asc")


def get_resolved_warehouse_names(selected_warehouses):
	warehouse_names = []
	for warehouse in selected_warehouses:
		warehouse_names.extend(warehouse.child_warehouses or [])

	return list(dict.fromkeys(warehouse_names))


def get_breakup_based_warehouses(breakup_stock_map):
	warehouse_names = []

	for warehouse_rows in breakup_stock_map.values():
		for warehouse_name, qty in warehouse_rows.items():
			if not flt(qty):
				continue
			warehouse_names.append(warehouse_name)

	ordered_names = list(dict.fromkeys(warehouse_names))

	return [
		frappe._dict(
			{
				"name": warehouse_name,
				"is_group": 0,
				"fieldname": f"warehouse_{scrub(warehouse_name)}",
				"label": warehouse_name,
				"child_warehouses": [warehouse_name],
			}
		)
		for warehouse_name in ordered_names
	]


def parse_multi_select(value):
	if not value:
		return []

	if isinstance(value, list):
		return [row for row in value if row]

	if isinstance(value, str):
		value = value.strip()
		if not value:
			return []

		if value.startswith("["):
			try:
				return [row for row in json.loads(value) if row]
			except Exception:
				pass

		return [row.strip() for row in value.split(",") if row.strip()]

	return []


def collect_item_codes(bom_no, item_codes, bom_cache, max_depth, level=0, visited=None):
	if level > max_depth:
		return

	visited = visited or set()
	if bom_no in visited:
		return

	visited.add(bom_no)
	bom_doc = get_bom_doc(bom_no, bom_cache)
	item_codes.add(bom_doc.item)

	for item in bom_doc.items:
		item_codes.add(item.item_code)
		if item.bom_no:
			collect_item_codes(item.bom_no, item_codes, bom_cache, max_depth, level + 1, visited.copy())

	for scrap_item in bom_doc.scrap_items:
		item_codes.add(scrap_item.item_code)


def get_bom_doc(bom_no, bom_cache):
	if bom_no not in bom_cache:
		bom_cache[bom_no] = frappe.get_cached_doc("BOM", bom_no)
	return bom_cache[bom_no]


def get_total_stock_map(item_codes, filters):
	if not item_codes:
		return {}

	conditions = ["item_code IN %(item_codes)s"]
	values = {"item_codes": tuple(item_codes)}

	selected_warehouses = filters.get("resolved_warehouse_names") or []
	if selected_warehouses:
		conditions.append("warehouse IN %(warehouses)s")
		values["warehouses"] = tuple(selected_warehouses)
	elif filters.get("company"):
		conditions.append(
			"warehouse IN (SELECT name FROM `tabWarehouse` WHERE company = %(company)s AND is_group = 0 AND disabled = 0)"
		)
		values["company"] = filters.company

	stock_rows = frappe.db.sql(
		f"""
		SELECT
			item_code,
			SUM(actual_qty) AS actual_qty
		FROM `tabBin`
		WHERE {" AND ".join(conditions)}
		GROUP BY item_code
		""",
		values,
		as_dict=True,
	)

	return {row.item_code: flt(row.actual_qty) for row in stock_rows}


def get_breakup_stock_map(item_codes, filters):
	if not item_codes:
		return {}

	conditions = ["bin.item_code IN %(item_codes)s"]
	values = {"item_codes": tuple(item_codes)}

	selected_warehouses = filters.get("resolved_warehouse_names") or []
	if selected_warehouses:
		conditions.append("bin.warehouse IN %(warehouses)s")
		values["warehouses"] = tuple(selected_warehouses)
	elif filters.get("company"):
		conditions.append("warehouse.company = %(company)s")
		values["company"] = filters.company

	stock_rows = frappe.db.sql(
		f"""
		SELECT
			bin.item_code,
			bin.warehouse,
			SUM(bin.actual_qty) AS actual_qty
		FROM `tabBin` bin
		INNER JOIN `tabWarehouse` warehouse ON warehouse.name = bin.warehouse
		WHERE {" AND ".join(conditions)}
		GROUP BY bin.item_code, bin.warehouse
		""",
		values,
		as_dict=True,
	)

	stock_map = {}
	for row in stock_rows:
		stock_map.setdefault(row.item_code, {})[row.warehouse] = flt(row.actual_qty)

	return stock_map


def get_warehouse_stock_map(item_codes, warehouses, breakup_stock_map):
	if not item_codes or not warehouses:
		return {}

	stock_map = {}

	for item_code, warehouse_rows in breakup_stock_map.items():
		for warehouse in warehouses:
			total_qty = sum(flt(warehouse_rows.get(child_warehouse)) for child_warehouse in warehouse.child_warehouses)
			if total_qty:
				stock_map.setdefault(item_code, {})[warehouse.name] = flt(total_qty)

	return stock_map


def build_tree_data(boms, total_stock_map, breakup_stock_map, warehouse_stock_map, warehouses, bom_cache, max_depth):
	data = []
	for bom in boms:
		total_stock, warehouse_stock, warehouse_breakup = get_row_stock(
			bom.item, total_stock_map, breakup_stock_map, warehouse_stock_map, warehouses
		)
		data.append(
			make_row(
				indent=0,
				bom_no=bom.name,
				item_code=bom.item,
				item_name=bom.item_name,
				row_type="BOM",
				linked_bom=bom.name,
				qty=bom.quantity,
				stock_uom=bom.uom,
				total_actual_stock=total_stock,
				warehouse_breakup=warehouse_breakup,
				warehouse_stock=warehouse_stock,
			)
		)

		data.append(
			make_row(
				indent=1,
				bom_no=bom.name,
				item_code=bom.item,
				item_name=bom.item_name,
				row_type="FG",
				linked_bom=bom.name,
				qty=bom.quantity,
				stock_uom=bom.uom,
				total_actual_stock=total_stock,
				warehouse_breakup=warehouse_breakup,
				warehouse_stock=warehouse_stock,
			)
		)

		append_bom_items(
			data=data,
			bom_no=bom.name,
			parent_indent=1,
			total_stock_map=total_stock_map,
			breakup_stock_map=breakup_stock_map,
			warehouse_stock_map=warehouse_stock_map,
			warehouses=warehouses,
			bom_cache=bom_cache,
			max_depth=max_depth,
		)

	return data


def append_bom_items(
	data,
	bom_no,
	parent_indent,
	total_stock_map,
	breakup_stock_map,
	warehouse_stock_map,
	warehouses,
	bom_cache,
	max_depth,
	level=1,
	visited=None,
):
	if level > max_depth:
		return

	visited = visited or set()
	if bom_no in visited:
		return

	visited.add(bom_no)
	bom_doc = get_bom_doc(bom_no, bom_cache)

	for item in bom_doc.items:
		total_stock, warehouse_stock, warehouse_breakup = get_row_stock(
			item.item_code, total_stock_map, breakup_stock_map, warehouse_stock_map, warehouses
		)
		row_type = "SFG" if item.bom_no else "RM"

		data.append(
			make_row(
				indent=parent_indent + 1,
				bom_no=bom_doc.name,
				item_code=item.item_code,
				item_name=item.item_name,
				row_type=row_type,
				linked_bom=item.bom_no,
				qty=item.qty,
				stock_uom=item.uom,
				total_actual_stock=total_stock,
				warehouse_breakup=warehouse_breakup,
				warehouse_stock=warehouse_stock,
			)
		)

		if item.bom_no:
			append_bom_items(
				data=data,
				bom_no=item.bom_no,
				parent_indent=parent_indent + 1,
				total_stock_map=total_stock_map,
				breakup_stock_map=breakup_stock_map,
				warehouse_stock_map=warehouse_stock_map,
				warehouses=warehouses,
				bom_cache=bom_cache,
				max_depth=max_depth,
				level=level + 1,
				visited=visited.copy(),
			)


def get_row_stock(item_code, total_stock_map, breakup_stock_map, warehouse_stock_map, warehouses):
	item_stock = warehouse_stock_map.get(item_code, {})
	item_breakup = breakup_stock_map.get(item_code, {})
	warehouse_stock = {}
	total_stock = flt(total_stock_map.get(item_code))

	for warehouse in warehouses:
		qty = flt(item_stock.get(warehouse.name))
		warehouse_stock[warehouse.fieldname] = qty

	return total_stock, warehouse_stock, format_warehouse_breakup(item_breakup)


def format_warehouse_breakup(item_breakup, limit=5):
	if not item_breakup:
		return ""

	sorted_rows = sorted(
		((warehouse, flt(qty)) for warehouse, qty in item_breakup.items() if flt(qty)),
		key=lambda row: abs(row[1]),
		reverse=True,
	)

	if not sorted_rows:
		return ""

	visible_rows = sorted_rows[:limit]
	breakup = " | ".join(
		f"{get_warehouse_short_name(warehouse)}: {qty:,.3f}" for warehouse, qty in visible_rows
	)

	if len(sorted_rows) > limit:
		breakup += _(" | +{0} more").format(len(sorted_rows) - limit)

	return breakup


def get_warehouse_short_name(warehouse):
	return warehouse.split(" - ")[0].strip() if " - " in warehouse else warehouse


def make_row(
	indent,
	bom_no,
	item_code,
	item_name,
	row_type,
	linked_bom,
	qty,
	stock_uom,
	total_actual_stock,
	warehouse_breakup,
	warehouse_stock,
):
	row = {
		"indent": indent,
		"bom_no": bom_no,
		"item_code": item_code,
		"item_name": item_name,
		"row_type": row_type,
		"linked_bom": linked_bom,
		"qty": flt(qty),
		"stock_uom": stock_uom,
		"total_actual_stock": flt(total_actual_stock),
		"warehouse_breakup": warehouse_breakup,
	}
	row.update(warehouse_stock)
	return row
