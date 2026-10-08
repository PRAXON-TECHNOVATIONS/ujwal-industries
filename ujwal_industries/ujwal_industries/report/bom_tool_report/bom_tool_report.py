from frappe import _

from ujwal_industries.ujwal_industries.api.bom_tool_data import get_bom_tool_rows


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters or {})
	return columns, data


def get_columns():
	return [
		{
			"label": _("FG Part No"),
			"fieldname": "fg_part_no",
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Part No"),
			"fieldname": "part_no",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Operation"),
			"fieldname": "operation",
			"fieldtype": "Link",
			"options": "Operation",
			"width": 160,
		},
		{
			"label": _("Tool No"),
			"fieldname": "tool",
			"fieldtype": "Link",
			"options": "Asset",
			"width": 180,
		},
		{
			"label": _("Qty Produced"),
			"fieldname": "qty_produced",
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 160,
		},
	]


def get_data(filters):
	flat_rows = get_bom_tool_rows(filters)

	# reshape the flat FG+Operation+Tool rows into a FG -> Operation -> Tool tree
	fg_map = {}
	for row in flat_rows:
		fg = fg_map.setdefault(
			row["fg_part_no"],
			{"item_name": row["item_name"], "part_no": row["part_no"], "operations": {}},
		)
		fg["operations"].setdefault(row["operation"], []).append(row)

	data = []
	for fg_part_no, fg in fg_map.items():
		data.append(
			{
				"indent": 0,
				"fg_part_no": fg_part_no,
				"item_name": fg["item_name"],
				"part_no": fg["part_no"],
			}
		)

		for operation, tool_rows in fg["operations"].items():
			data.append(
				{
					"indent": 1,
					"operation": operation,
				}
			)

			for tool_row in tool_rows:
				data.append(
					{
						"indent": 2,
						"tool": tool_row["tool"],
						"qty_produced": tool_row["qty_produced"],
						"status": tool_row["status"],
					}
				)

	return data
