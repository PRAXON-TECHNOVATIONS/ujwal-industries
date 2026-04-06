import json

import frappe
from frappe import _, scrub
from frappe.utils import cint, flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.warehouses = parse_multi_select(filters.get("warehouses"))
	filters.max_depth = cint(filters.get("max_depth") or 10)

	warehouses = get_warehouses(filters)
	boms = get_boms(filters)

	if not boms:
		return get_columns([]), []

	item_codes = set()
	bom_cache = {}
	for bom in boms:
		collect_item_codes(bom.name, item_codes, bom_cache, filters.max_depth)
		item_codes.add(bom.item)

	stock_map = get_stock_map(item_codes, warehouses)
	columns = get_columns(warehouses)
	data = build_tree_data(boms, stock_map, warehouses, bom_cache, filters.max_depth)

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


def get_warehouses(filters):
	selected_warehouses = filters.get("warehouses") or []
	warehouse_filters = {"is_group": 0, "disabled": 0}

	if filters.get("company"):
		warehouse_filters["company"] = filters.company

	if selected_warehouses:
		warehouse_filters["name"] = ["in", selected_warehouses]

	warehouses = frappe.get_all(
		"Warehouse",
		filters=warehouse_filters,
		fields=["name"],
		order_by="name asc",
	)

	return [
		frappe._dict(
			{
				"name": warehouse.name,
				"fieldname": f"warehouse_{scrub(warehouse.name)}",
				"label": warehouse.name,
			}
		)
		for warehouse in warehouses
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


def get_stock_map(item_codes, warehouses):
	if not item_codes:
		return {}

	warehouse_names = [warehouse.name for warehouse in warehouses]
	if not warehouse_names:
		return {}

	stock_rows = frappe.db.sql(
		"""
		SELECT
			item_code,
			warehouse,
			SUM(actual_qty) AS actual_qty
		FROM `tabBin`
		WHERE item_code IN %(item_codes)s
			AND warehouse IN %(warehouses)s
		GROUP BY item_code, warehouse
		""",
		{"item_codes": tuple(item_codes), "warehouses": tuple(warehouse_names)},
		as_dict=True,
	)

	stock_map = {}
	for row in stock_rows:
		stock_map.setdefault(row.item_code, {})[row.warehouse] = flt(row.actual_qty)

	return stock_map


def build_tree_data(boms, stock_map, warehouses, bom_cache, max_depth):
	data = []
	for bom in boms:
		total_stock, warehouse_stock = get_row_stock(bom.item, stock_map, warehouses)
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
				warehouse_stock=warehouse_stock,
			)
		)

		append_bom_items(
			data=data,
			bom_no=bom.name,
			parent_indent=1,
			stock_map=stock_map,
			warehouses=warehouses,
			bom_cache=bom_cache,
			max_depth=max_depth,
		)

	return data


def append_bom_items(data, bom_no, parent_indent, stock_map, warehouses, bom_cache, max_depth, level=1, visited=None):
	if level > max_depth:
		return

	visited = visited or set()
	if bom_no in visited:
		return

	visited.add(bom_no)
	bom_doc = get_bom_doc(bom_no, bom_cache)

	for item in bom_doc.items:
		total_stock, warehouse_stock = get_row_stock(item.item_code, stock_map, warehouses)
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
				warehouse_stock=warehouse_stock,
			)
		)

		if item.bom_no:
			append_bom_items(
				data=data,
				bom_no=item.bom_no,
				parent_indent=parent_indent + 1,
				stock_map=stock_map,
				warehouses=warehouses,
				bom_cache=bom_cache,
				max_depth=max_depth,
				level=level + 1,
				visited=visited.copy(),
			)

	append_scrap_items(
		data=data,
		bom_doc=bom_doc,
		indent=parent_indent + 1,
		stock_map=stock_map,
		warehouses=warehouses,
	)


def append_scrap_items(data, bom_doc, indent, stock_map, warehouses):
	for scrap_item in bom_doc.scrap_items:
		total_stock, warehouse_stock = get_row_stock(scrap_item.item_code, stock_map, warehouses)
		data.append(
			make_row(
				indent=indent,
				bom_no=bom_doc.name,
				item_code=scrap_item.item_code,
				item_name=scrap_item.item_name,
				row_type="Scrap",
				linked_bom="",
				qty=scrap_item.stock_qty,
				stock_uom=scrap_item.stock_uom,
				total_actual_stock=total_stock,
				warehouse_stock=warehouse_stock,
			)
		)


def get_row_stock(item_code, stock_map, warehouses):
	item_stock = stock_map.get(item_code, {})
	warehouse_stock = {}
	total_stock = 0

	for warehouse in warehouses:
		qty = flt(item_stock.get(warehouse.name))
		warehouse_stock[warehouse.fieldname] = qty
		total_stock += qty

	return total_stock, warehouse_stock


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
	}
	row.update(warehouse_stock)
	return row
