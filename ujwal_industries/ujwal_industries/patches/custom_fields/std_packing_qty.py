import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Std Packing Qty is maintained on the Item master and fetched onto Sales
	# Invoice rows. The Sales Invoice packing-label print format splits each
	# row's qty into labels of this size (row value first, Item value fallback).
	row_field = {
		"fieldname": "custom_std_packing_qty",
		"fieldtype": "Float",
		"label": "Std Packing Qty",
		"insert_after": "uom",
		"fetch_from": "item_code.custom_std_packing_qty",
		"fetch_if_empty": 1,
		"non_negative": 1,
	}
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "custom_std_packing_qty",
					"fieldtype": "Float",
					"label": "Std Packing Qty",
					"insert_after": "custom_part_number",
					"non_negative": 1,
					"description": "Qty per pack / label. Used to split packing labels.",
				}
			],
			"Sales Invoice Item": [row_field],
		},
		ignore_validate=True,
	)
