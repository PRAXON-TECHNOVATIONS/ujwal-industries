import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_work_order_scrap_status(work_order):

    rows = []

    if not work_order:
        return []

    # 1️⃣ Job Card Completed Qty (WO level)
    job_cards = frappe.get_all(
        "Job Card",
        filters={"work_order": work_order, "docstatus": 1},
        fields=["total_completed_qty"]
    )
    wo_completed_qty = sum(flt(j.total_completed_qty) for j in job_cards)

    # 2️⃣ Work Order + BOM
    wo = frappe.get_doc("Work Order", work_order)
    if not wo.bom_no:
        return []

    bom = frappe.get_doc("BOM", wo.bom_no)
    bom_qty = flt(bom.quantity) or 1

    # 3️⃣ Scrap item (single scrap item as discussed)
    if not bom.scrap_items:
        return []

    scrap = bom.scrap_items[0]
    scrap_item_code = scrap.item_code
    scrap_item_name = frappe.db.get_value("Item", scrap_item_code, "item_name")

    # 4️⃣ Manufacture Stock Entries only
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

    # keep only entries where FG actually produced
    stock_entries = [
        se for se in stock_entries
        if flt(se.fg_completed_qty) > 0
    ]

    total_expected = 0
    total_actual = 0

    # 5️⃣ One row per Stock Entry
    for se in stock_entries:

        manufactured_qty = flt(se.fg_completed_qty)

        # ✅ Correct expected scrap PER ENTRY
        expected_qty = (manufactured_qty / bom_qty) * flt(scrap.stock_qty)

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

        rows.append({
            "scrap_item_code": scrap_item_code,
            "scrap_item_name": scrap_item_name,
            "stock_entry": se.name,
            "expected_scrap_qty": round(expected_qty, 3),
            "completed_qty": manufactured_qty,
            "actual_scrap_qty": round(actual_qty, 3),
            "status": ""  # filled later
        })

    # 6️⃣ WO-level status
    if total_actual == 0:
        status = "Scrap Not Received"
    elif total_actual < total_expected:
        status = "Partial Received"
    else:
        status = "Fully Received"

    for r in rows:
        r["status"] = status

    # 7️⃣ TOTAL ROW (ONLY ONCE, CORRECT)
    rows.append({
        "scrap_item_code": "",
        "scrap_item_name": "TOTAL",
        "stock_entry": "",
        "expected_scrap_qty": round(total_expected, 3),
        "completed_qty": "",
        "actual_scrap_qty": round(total_actual, 3),
        "status": status
    })

    return rows
