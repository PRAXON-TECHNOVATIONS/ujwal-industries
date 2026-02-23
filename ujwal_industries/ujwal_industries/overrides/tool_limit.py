
import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils import get_datetime
from frappe.utils import getdate, nowdate

@frappe.whitelist()
def validate_tool_limit(docname):
    
    doc = frappe.get_doc("Production Plan", docname)

    messages = []

    for row in doc.po_items:

        if not row.bom_no:
            continue

        tool_details = frappe.get_all(
            "Tool Child Table",
            filters={"parent": row.bom_no},
            fields=["tool", "tool_load_quantity"]
        )

        for tool in tool_details:

            previous_qty = frappe.db.sql("""
                SELECT SUM(ai.planned_qty)
                FROM `tabProduction Plan` pp
                JOIN `tabProduction Plan Item` ai ON ai.parent = pp.name
                WHERE pp.docstatus = 1
                AND ai.bom_no = %s
                AND pp.name != %s
            """, (row.bom_no, doc.name))[0][0] or 0

            total_usage = flt(previous_qty) + flt(row.planned_qty)

            if total_usage > flt(tool.tool_load_quantity):

                messages.append(f"""
                    <b>Tool:</b> {tool.tool}<br>
                    Allowed: {tool.tool_load_quantity}<br>
                    Already Used: {previous_qty}<br>
                    Current Qty: {row.planned_qty}<br>
                    <b>Total:</b> {total_usage}<br>
                """)
    return messages




def validate_tool_conflict(doc, method):
    if not doc.sub_assembly_items:
        return

    for row in doc.sub_assembly_items:

        if not row.schedule_date or not row.custom_schedule_end_date or not row.bom_no:
            continue

        new_start = get_datetime(row.schedule_date)
        new_end = get_datetime(row.custom_schedule_end_date)

        tools = frappe.get_all(
            "Tool Child Table",
            filters={"parent": row.bom_no},
            pluck="tool"
        )

        if not tools:
            continue

        for tool in tools:

            conflict = frappe.db.sql("""
                SELECT
                    pp.name,
                    sai.schedule_date,
                    sai.custom_schedule_end_date
                FROM
                    `tabProduction Plan` pp
                INNER JOIN
                    `tabProduction Plan Sub Assembly Item` sai 
                        ON sai.parent = pp.name
                INNER JOIN
                    `tabTool Child Table` btd 
                        ON btd.parent = sai.bom_no
                WHERE
                    pp.docstatus = 1
                    AND pp.name != %s
                    AND sai.bom_no = %s       
                    AND btd.tool = %s
                    AND sai.schedule_date <= %s
                    AND sai.custom_schedule_end_date >= %s
            """, (
                doc.name,
                row.bom_no,  
                tool,
                new_end,
                new_start
            ), as_dict=True)

            if conflict:
                frappe.throw(_(
                    f"Tool <b>{tool}</b> from BOM <b>{row.bom_no}</b> "
                    f"is already allocated in Production Plan "
                    f"<b>{conflict[0].name}</b> "
                ))
                

def fetched_default_bom(doc, method):
    if not doc.sub_assembly_items:
        return

    for row in doc.sub_assembly_items:
        if not row.bom_no:
            continue

        default_tool = frappe.get_all("Tool Child Table",
            filters={
                "parent": row.bom_no,
                "is_default": 1
            }, fields=["tool"],limit=1)
        
        if default_tool:
            row.custom_tool = default_tool[0].tool
                        



def validate_tool_maintenance(doc, method):
    if not doc.sub_assembly_items:
        return

    today = getdate(nowdate())
    for row in doc.sub_assembly_items:
        if not row.custom_tool:
            continue

        maintenances = frappe.get_all("Asset Maintenance",filters={"asset_name": row.custom_tool,}, pluck="name")
        for maint_name in maintenances:
            maint_doc = frappe.get_doc("Asset Maintenance", maint_name)

            for task in maint_doc.asset_maintenance_tasks:
                if not task.start_date or not task.end_date:
                    continue

                start = getdate(task.start_date)
                end = getdate(task.end_date)

                if start <= today <= end:
                    frappe.throw(
                        _("Row {0}: Tool <b>{1}</b> is under maintenance "
                          "from {2} to {3}.")
                        .format(row.idx,row.custom_tool, start,end))


@frappe.whitelist()                
def tool_conflict(name, bom, row_name, from_doctype):
    conflict = []
    doc = frappe.get_doc("Production Plan", name)
    
    if from_doctype == 'sub_assembly_items':
        if not doc.sub_assembly_items:
            return

        for row in doc.sub_assembly_items:
            if row.name== row_name and row.type_of_manufacturing == 'In House':

                if not row.schedule_date or not row.custom_schedule_end_date or not bom:
                    continue

                new_start = get_datetime(row.schedule_date)
                new_end = get_datetime(row.custom_schedule_end_date)

                tools = frappe.get_all(
                    "Tool Child Table",
                    filters={"parent": bom},
                    pluck="tool"
                )

                if not tools:
                    continue

                for tool in tools:

                    conflict = frappe.db.sql("""
                        SELECT
                            pp.name,
                            sai.schedule_date,
                            sai.custom_schedule_end_date,
                            sai.bom_no,
                            btd.tool,
                            btd.operation
                            
                        FROM
                            `tabProduction Plan` pp
                        INNER JOIN
                            `tabProduction Plan Sub Assembly Item` sai 
                                ON sai.parent = pp.name
                        INNER JOIN
                            `tabTool Child Table` btd 
                                ON btd.parent = sai.bom_no
                        WHERE
                            pp.docstatus = 1
                            AND pp.name != %s
                            AND sai.bom_no = %s       
                            AND btd.tool = %s
                            AND sai.schedule_date <= %s
                            AND sai.custom_schedule_end_date >= %s
                    """, (
                        doc.name,
                        bom,  
                        tool,
                        new_end,
                        new_start
                    ), as_dict=True)
                    
                    
    else:
        if not doc.po_items:
            return

        for row in doc.po_items:
            if row.name== row_name and row.custom_manufacturing_type == 'In House':

                if not row.planned_start_date or not row.custom_planned_end_date or not bom:
                    continue

                new_start = get_datetime(row.planned_start_date)
                new_end = get_datetime(row.custom_planned_end_date)

                tools = frappe.get_all(
                    "Tool Child Table",
                    filters={"parent": bom},
                    pluck="tool"
                )

                if not tools:
                    continue

                for tool in tools:

                    conflict = frappe.db.sql("""
                        SELECT
                            pp.name,
                            sai.planned_start_date,
                            sai.custom_planned_end_date,
                            sai.bom_no,
                            btd.tool,
                            btd.operation
                            
                        FROM
                            `tabProduction Plan` pp
                        INNER JOIN
                            `tabProduction Plan Item` sai 
                                ON sai.parent = pp.name
                        INNER JOIN
                            `tabTool Child Table` btd 
                                ON btd.parent = sai.bom_no
                        WHERE
                            pp.docstatus = 1
                            AND pp.name != %s
                            AND sai.bom_no = %s       
                            AND btd.tool = %s
                            AND sai.planned_start_date <= %s
                            AND sai.custom_planned_end_date >= %s
                    """, (
                        doc.name,
                        bom,  
                        tool,
                        new_end,
                        new_start
                    ), as_dict=True)
                        
                
    return conflict
                
                
@frappe.whitelist()
def get_bom_tools(doctype, txt, searchfield, start, page_len, filters):
    if not filters.get("bom"):
        return []

    tools = frappe.get_all("Tool Child Table",filters={"parent": filters.get("bom")}, pluck="tool")
    if not tools:
        return []

    x =  frappe.db.sql("""
        SELECT name
        FROM `tabAsset`
        WHERE name IN %(tools)s
        AND name LIKE %(txt)s
        LIMIT %(start)s, %(page_len)s
    """, {
        "tools": tuple(tools),
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })  
    return x              