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
    if not filters:
        filters = {}
        
    data = []  
    
    conditions = " "
    query_filters = {}
    
    if filters.get("tool"):
        conditions += " AND tct.tool = %(tool)s"
        query_filters["tool"] = filters.get("tool")
        
    bom = frappe.db.sql(f"""
        SELECT 
            tb.item,
            tct.tool,
            tct.tool_load_quantity
        FROM `tabBOM` tb
        LEFT JOIN `tabTool Child Table` tct ON tct.parent = tb.name
        WHERE tb.is_default = 1 {conditions}
    """, query_filters, as_dict=True)

    for i in bom:
        data.append({
            'indent': 0,
            'item_name': i.item,
        })
        
        data.append({
            'indent': 1,
            'tool': i.tool,
            'tool_load_capacity_qty': i.tool_load_quantity,
        })
   
    
    return data
        
