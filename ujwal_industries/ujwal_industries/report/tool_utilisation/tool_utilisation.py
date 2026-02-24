# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns(filters=None):
    return [
        {
            "label": _("Item Name"),
            "fieldname": "item_name",
            "fieldtype": "Link",
            "options": "Item",
            "width": 200,
        },
        {
            "label": _("Tool"),
            "fieldname": "tool",
            "fieldtype": "Link",
            "options": "Asset",
            "width": 200,
        },
        {
            "label": _("Tool Load Capacity Qty"),
            "fieldname": "tool_load_capacity_qty",
            "fieldtype": "Int",
            "width": 200,
        },
        {
            "label": _("Balance Quantity"),
            "fieldname": "balance_quantity",
            "fieldtype": "Int",
            "width": 200,
        },
        {
            "label": _("Reserve Qty"),
            "fieldname": "reserve_qty",
            "fieldtype": "Int",
            "width": 200,
        },
        {
            "label": _("Status"),
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 200,
        },
	]
    
def get_data(filters=None):
    data = []    
    data.append({
		'item_name': 'A',
	})
    
    return data
        
