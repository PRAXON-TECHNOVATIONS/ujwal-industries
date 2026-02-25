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
            "width": 100,
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
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    selected_tool = filters.get("tool")

    jobcard_filters = {"docstatus": ["!=", 2], "status": ["not in", ["Completed", "On Hold"]],}

    if from_date and to_date:
        jobcard_filters["expected_start_date"] = ["between", [from_date, to_date]]

    if selected_tool:
        jobcard_filters["custom_tool_name"] = selected_tool

    job_cards = frappe.get_all("Job Card", filters=jobcard_filters, fields=["bom_no", "custom_tool_name"])

    valid_pairs = {(jc.bom_no, jc.custom_tool_name) for jc in job_cards if jc.custom_tool_name}

    bom_records = frappe.db.sql("""
        SELECT 
            tb.name as bom_name,
            tb.item,
            tct.tool,
            tct.tool_load_quantity
        FROM `tabBOM` tb
        LEFT JOIN `tabTool Child Table` tct ON tct.parent = tb.name
        WHERE tb.is_default = 1
        ORDER BY tb.item
    """, as_dict=True)

    item_map = {}

    for row in bom_records:
        key = (row.bom_name, row.tool)

        if from_date and to_date:
            key = (row.bom_name, row.tool)
            if key not in valid_pairs:
                continue
            
        if selected_tool and row.tool != selected_tool:
            continue
        
        if row.item not in item_map:
            item_map[row.item] = []

        item_map[row.item].append(row)

    for item, tools in item_map.items():

        data.append({
            "indent": 0,
            "item_name": item
        })

        for tool_row in tools:

            status = ''
            if tool_row.tool:
                status = 'Open'
                
                maintenance_exists = frappe.db.exists("Asset Maintenance", {"asset_name": tool_row.tool,})
                if maintenance_exists:
                    status = "Maintenance"
                

                working_in_jobcard = frappe.db.exists("Job Card", {
                    "bom_no": tool_row.bom_name,
                    "custom_tool_name": tool_row.tool,
                    "docstatus": ["!=", 2],
                    "status": ["not in", ["Completed", "On Hold"]]
                })

                if working_in_jobcard:
                    status = "Working" 

            balance_qty = 0
            reserved_qty = 0
            
            balance_qty += frappe.db.sql( """SELECT IFNULL(sum(tppsai.qty), 0) as balance_qty
                                            FROM `tabProduction Plan Sub Assembly Item` tppsai 
                                            Left join `tabProduction Plan` tpp on tpp.name = tppsai.parent 
                                            WHERE tppsai.bom_no = '{0}' and tpp.status in ('Material Requested','In Process') """.format(tool_row.bom_name))[0][0]
            
            balance_qty += frappe.db.sql( """SELECT IFNULL(sum(tppi.planned_qty), 0) as balance_qty
                                            FROM `tabProduction Plan Item` tppi
                                            Left join `tabProduction Plan` tpp on tpp.name = tppi.parent 
                                            WHERE tppi.bom_no = '{0}' and tpp.status in ('Material Requested','In Process') """.format(tool_row.bom_name))[0][0]
            
            reserved_qty += frappe.db.sql( """SELECT IFNULL(sum(tppsai.qty), 0) as balance_qty
                                            FROM `tabProduction Plan Sub Assembly Item` tppsai 
                                            Left join `tabProduction Plan` tpp on tpp.name = tppsai.parent 
                                            WHERE tppsai.bom_no = '{0}' and tpp.status in ('Not Started') """.format(tool_row.bom_name))[0][0]
            
            reserved_qty += frappe.db.sql( """SELECT IFNULL(sum(tppi.planned_qty), 0) as balance_qty
                                            FROM `tabProduction Plan Item` tppi
                                            Left join `tabProduction Plan` tpp on tpp.name = tppi.parent 
                                            WHERE tppi.bom_no = '{0}' and tpp.status in ('Not Started') """.format(tool_row.bom_name))[0][0]
             

            data.append({
                "indent": 1,
                "tool": tool_row.tool,
                "tool_load_capacity_qty": tool_row.tool_load_quantity,
                "balance_quantity": balance_qty,
                "reserve_qty": reserved_qty,
                "status": status
            })

    return data