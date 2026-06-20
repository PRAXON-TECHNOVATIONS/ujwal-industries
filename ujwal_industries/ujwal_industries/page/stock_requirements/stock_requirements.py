import frappe
from frappe.utils import flt, getdate, nowdate


@frappe.whitelist()
def get_stock_requirements(item_code, warehouse):
    """
    MD04-style Stock/Requirements List for a single item + warehouse.
    Returns opening stock + chronological list of MRP elements with running
    available-quantity balance.
    """
    if not item_code or not warehouse:
        frappe.throw("Item Code and Warehouse are required")

    today = getdate(nowdate())
    rows = []

    # ── 1. Opening stock ──────────────────────────────────────────────────
    opening_qty = _get_actual_stock(item_code, warehouse)

    # ── 2. Gather all MRP elements ────────────────────────────────────────
    rows += _get_purchase_orders(item_code, warehouse)
    rows += _get_purchase_requisitions(item_code, warehouse)
    rows += _get_work_orders_receipt(item_code, warehouse)
    rows += _get_stock_entries_receipt(item_code, warehouse)
    rows += _get_sales_orders(item_code, warehouse)
    rows += _get_material_requests(item_code, warehouse)

    # ── 3. Sort by date, then by direction (receipts before requirements on same day) ──
    def sort_key(r):
        d = r.get("date") or "9999-12-31"
        # receipts (positive qty) sort before requirements on same date
        direction = 0 if flt(r.get("qty", 0)) > 0 else 1
        return (str(d), direction, r.get("document_type", ""))

    rows.sort(key=sort_key)

    # ── 4. Compute running available qty ─────────────────────────────────
    running = flt(opening_qty)
    for r in rows:
        running += flt(r.get("qty", 0))
        r["available_qty"] = running

    # ── 5. Item details ───────────────────────────────────────────────────
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "stock_uom", "item_group", "description"],
        as_dict=True,
    ) or {}

    return {
        "item_code": item_code,
        "item_name": item.get("item_name", ""),
        "stock_uom": item.get("stock_uom", ""),
        "item_group": item.get("item_group", ""),
        "warehouse": warehouse,
        "opening_qty": flt(opening_qty),
        "as_of_date": str(today),
        "rows": rows,
    }


@frappe.whitelist()
def get_bom_tree(item_code):
    """
    Recursively explode the default/active BOM of an item into a tree of
    {item_code, item_name, bom_no, qty, uom, children}.
    """
    if not item_code:
        frappe.throw("Item Code is required")

    visited = set()
    tree = _build_bom_node(item_code, qty=1, visited=visited)

    return tree


def _build_bom_node(item_code, qty, visited):
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "stock_uom"],
        as_dict=True,
    ) or {}

    bom_no = frappe.db.get_value(
        "BOM",
        {"item": item_code, "is_active": 1, "is_default": 1},
        "name",
    )

    if not bom_no:
        bom_no = frappe.db.get_value(
            "BOM",
            {"item": item_code, "is_active": 1},
            "name",
        )

    node = {
        "item_code": item_code,
        "item_name": item.get("item_name", ""),
        "uom": item.get("stock_uom", ""),
        "qty": flt(qty),
        "bom_no": bom_no,
        "children": [],
    }

    if not bom_no:
        return node

    # Prevent infinite loops on circular BOM references
    if bom_no in visited:
        return node
    visited = visited | {bom_no}

    bom_items = frappe.db.sql("""
        SELECT
            bi.item_code,
            bi.qty
        FROM `tabBOM Item` bi
        WHERE bi.parent = %s
          AND bi.docstatus < 2
        ORDER BY bi.idx
    """, (bom_no,), as_dict=True)

    for bi in bom_items:
        child_qty = flt(bi.qty) * flt(qty)
        node["children"].append(
            _build_bom_node(bi.item_code, child_qty, visited)
        )

    return node




def _get_actual_stock(item_code, warehouse):
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(actual_qty), 0)
        FROM `tabBin`
        WHERE item_code = %s AND warehouse = %s
    """, (item_code, warehouse))
    return flt(result[0][0]) if result else 0.0


# ─── Receipts ─────────────────────────────────────────────────────────────────

def _get_purchase_orders(item_code, warehouse):
    rows = frappe.db.sql("""
        SELECT
            poi.parent          AS document_name,
            poi.schedule_date   AS date,
            (poi.qty - poi.received_qty) AS qty,
            poi.uom,
            poi.rate,
            po.supplier         AS party,
            po.status
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE poi.item_code = %s
          AND poi.warehouse = %s
          AND po.docstatus = 1
          AND po.status NOT IN ('Completed', 'Cancelled', 'Closed')
          AND (poi.qty - poi.received_qty) > 0
    """, (item_code, warehouse), as_dict=True)

    return [
        {
            "document_type": "Purchase Order",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": flt(r.qty),
            "uom": r.uom,
            "rate": flt(r.rate),
            "party": r.party,
            "status": r.status,
            "direction": "receipt",
            "icon": "po",
        }
        for r in rows
        if flt(r.qty) > 0
    ]


def _get_purchase_requisitions(item_code, warehouse):
    rows = frappe.db.sql("""
        SELECT
            mri.parent          AS document_name,
            mri.schedule_date   AS date,
            mri.qty,
            mri.uom,
            mr.status
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE mri.item_code = %s
          AND mri.warehouse = %s
          AND mr.docstatus = 1
          AND mr.material_request_type = 'Purchase'
          AND mr.status NOT IN ('Ordered', 'Cancelled', 'Stopped')
    """, (item_code, warehouse), as_dict=True)

    return [
        {
            "document_type": "Purchase Requisition",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": flt(r.qty),
            "uom": r.uom,
            "rate": 0,
            "party": "",
            "status": r.status,
            "direction": "receipt",
            "icon": "pr",
        }
        for r in rows
    ]


def _get_work_orders_receipt(item_code, warehouse):
    rows = frappe.db.sql("""
        SELECT
            wo.name             AS document_name,
            wo.planned_end_date AS date,
            (wo.qty - wo.produced_qty) AS qty,
            wo.stock_uom        AS uom,
            wo.fg_warehouse     AS wh,
            wo.status
        FROM `tabWork Order` wo
        WHERE wo.production_item = %s
          AND wo.fg_warehouse = %s
          AND wo.docstatus = 1
          AND wo.status NOT IN ('Completed', 'Cancelled', 'Stopped')
          AND (wo.qty - wo.produced_qty) > 0
    """, (item_code, warehouse), as_dict=True)

    return [
        {
            "document_type": "Work Order",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": flt(r.qty),
            "uom": r.uom,
            "rate": 0,
            "party": "",
            "status": r.status,
            "direction": "receipt",
            "icon": "wo",
        }
        for r in rows
        if flt(r.qty) > 0
    ]


def _get_stock_entries_receipt(item_code, warehouse):
    """Draft stock entries that will add stock (Material Receipt / Material Transfer In)."""
    rows = frappe.db.sql("""
        SELECT
            sed.parent          AS document_name,
            se.posting_date     AS date,
            sed.qty,
            sed.uom,
            se.stock_entry_type AS entry_type
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE sed.item_code = %s
          AND sed.t_warehouse = %s
          AND se.docstatus = 0
          AND se.stock_entry_type IN ('Material Receipt', 'Material Transfer', 'Manufacture')
    """, (item_code, warehouse), as_dict=True)

    return [
        {
            "document_type": "Stock Entry",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": flt(r.qty),
            "uom": r.uom,
            "rate": 0,
            "party": "",
            "status": "Draft",
            "direction": "receipt",
            "icon": "se",
            "sub_type": r.entry_type,
        }
        for r in rows
    ]


# ─── Requirements ─────────────────────────────────────────────────────────────

def _get_sales_orders(item_code, warehouse):
    rows = frappe.db.sql("""
        SELECT
            soi.parent              AS document_name,
            so.delivery_date        AS date,
            (soi.qty - soi.delivered_qty) AS qty,
            soi.uom,
            soi.rate,
            so.customer             AS party,
            so.customer_name        AS party_name,
            so.status
        FROM `tabSales Order Item` soi
        JOIN `tabSales Order` so ON so.name = soi.parent
        WHERE soi.item_code = %s
          AND soi.warehouse = %s
          AND so.docstatus = 1
          AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
          AND (soi.qty - soi.delivered_qty) > 0
    """, (item_code, warehouse), as_dict=True)

    return [
        {
            "document_type": "Sales Order",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": -flt(r.qty),
            "uom": r.uom,
            "rate": flt(r.rate),
            "party": r.party,
            "party_name": r.party_name,
            "status": r.status,
            "direction": "requirement",
            "icon": "so",
        }
        for r in rows
        if flt(r.qty) > 0
    ]


def _get_material_requests(item_code, warehouse):
    """Internal material requests of type Issue (consume stock)."""
    rows = frappe.db.sql("""
        SELECT
            mri.parent          AS document_name,
            mri.schedule_date   AS date,
            mri.qty,
            mri.uom,
            mr.status
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE mri.item_code = %s
          AND mri.warehouse = %s
          AND mr.docstatus = 1
          AND mr.material_request_type = 'Material Issue'
          AND mr.status NOT IN ('Transferred', 'Issued', 'Cancelled', 'Stopped')
    """, (item_code, warehouse), as_dict=True)

    return [
        {
            "document_type": "Material Request",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": -flt(r.qty),
            "uom": r.uom,
            "rate": 0,
            "party": "",
            "status": r.status,
            "direction": "requirement",
            "icon": "mr",
        }
        for r in rows
    ]