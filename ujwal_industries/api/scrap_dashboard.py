import frappe
from frappe.utils import flt

@frappe.whitelist()
def get_work_order_scrap_status(work_order):
    rows = []

    if not work_order:
        return []

    # 1. Work Order + BOM Details
    wo = frappe.get_doc("Work Order", work_order)
    if not wo.bom_no:
        return []

    bom = frappe.get_doc("BOM", wo.bom_no)
    bom_qty = flt(bom.quantity) or 1

    # 2. Scrap Item Details
    if not bom.scrap_items:
        return []

    scrap = bom.scrap_items[0]
    scrap_item_code = scrap.item_code
    scrap_item_name = frappe.db.get_value("Item", scrap_item_code, "item_name")

    # 3. Manufacture Stock Entries
    stock_entries = frappe.get_all(
        "Stock Entry",
        filters={
            "work_order": work_order,
            "docstatus": 1,
            "stock_entry_type": "Manufacture",
            "bom_no": wo.bom_no
        },
        fields=["name", "fg_completed_qty"],
        order_by="posting_date, name"
    )

    stock_entries = [se for se in stock_entries if flt(se.fg_completed_qty) >= 0]

    total_expected = 0
    total_actual = 0
    total_manufactured = 0  # ✅ New Variable for Total Mfg Qty

    # 4. Loop through Stock Entries
    for se in stock_entries:
        manufactured_qty = flt(se.fg_completed_qty)
        total_manufactured += manufactured_qty  # ✅ Add to total

        # Expected Scrap for THIS entry
        expected_qty = (manufactured_qty / bom_qty) * flt(scrap.stock_qty)
        
        # Actual Scrap for THIS entry
        actual_qty = frappe.db.sql("""
            SELECT SUM(qty)
            FROM `tabStock Entry Detail`
            WHERE
                parent = %s
                AND is_scrap_item = 1
                AND item_code = %s
        """, (se.name, scrap_item_code))[0][0] or 0

        total_expected += expected_qty
        total_actual += actual_qty

        # ✅ Row-wise Status Logic
        if actual_qty == 0:
            row_status = "Scrap Not Received"
        elif actual_qty < expected_qty:
            row_status = "Partial Received"
        else:
            row_status = "Fully Received"

        rows.append({
            "scrap_item_code": scrap_item_code,
            "scrap_item_name": scrap_item_name,
            "stock_entry": se.name,
            "expected_scrap_qty": round(expected_qty, 3),
            "completed_qty": manufactured_qty,
            "actual_scrap_qty": round(actual_qty, 3),
            "status": row_status  # ✅ Individual Status
        })

    # 5. Global Status Logic (For Total Row)
    if total_actual == 0:
        global_status = "Scrap Not Received"
    elif total_actual < total_expected:
        global_status = "Partial Received"
    else:
        global_status = "Fully Received"

    # 6. Append Total Row
    rows.append({
        "scrap_item_code": "",
        "scrap_item_name": "<b>TOTAL</b>",
        "stock_entry": "",
        "expected_scrap_qty": round(total_expected, 3),
        "completed_qty": total_manufactured,  # ✅ Total Manufactured Qty Added
        "actual_scrap_qty": round(total_actual, 3),
        "status": global_status  # ✅ Overall Status
    })

    return rows