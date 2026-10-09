import frappe
from frappe.utils import flt, getdate, nowdate


@frappe.whitelist()
def get_stock_requirements(item_code, warehouse=None):
    """
    MD04-style Stock/Requirements List for a single item, in one warehouse
    or (when warehouse is blank) across all warehouses.
    Returns opening stock + chronological list of MRP elements with running
    available-quantity balance.
    """
    if not item_code:
        frappe.throw("Item Code is required")
    warehouse = warehouse or ""

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
        r["in_mrp"] = 1

    # ── 4b. Every other non-cancelled document of the item (drafts, completed…)
    # is listed too, but does not move the running balance.
    in_table = {(r.get("doctype") or r["document_type"], r["document_name"]) for r in rows}
    for d in get_related_documents(item_code):
        if (d["doctype"], d["name"]) not in in_table:
            in_table.add((d["doctype"], d["name"]))
            rows.append(_related_to_row(d))
    rows.sort(key=lambda r: (r.get("date") or "9999-12-31")[:10])  # stable: MRP order kept

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
def get_default_warehouse(item_code, company=None):
    """
    Resolve the most relevant warehouse for an item, used when drilling into a
    BOM-tree child whose stock is kept in a different warehouse than the root
    item (e.g. raw materials kept in RM Store while the FG is kept in FG Store).
    """
    if not item_code:
        frappe.throw("Item Code is required")

    filters = {"parent": item_code}
    if company:
        filters["company"] = company

    warehouse = frappe.db.get_value("Item Default", filters, "default_warehouse")

    if not warehouse and company:
        # Retry without the company filter in case Item Default has no row for it
        warehouse = frappe.db.get_value("Item Default", {"parent": item_code}, "default_warehouse")

    return warehouse


@frappe.whitelist()
def get_bom_tree(item_code):
    """
    Recursively explode the default/active BOM of an item into a tree of
    {item_code, item_name, bom_no, qty, uom, children}.
    """
    if not item_code:
        frappe.throw("Item Code is required")

    # Root is shown at its BOM's batch quantity, so every level matches the BOM documents
    root_bom = _get_bom(item_code)
    root_qty = flt(frappe.db.get_value("BOM", root_bom, "quantity")) if root_bom else 1

    visited = set()
    tree = _build_bom_node(item_code, qty=root_qty or 1, visited=visited)

    return tree


def _get_bom(item_code):
    """Default active BOM of the item, else any active one."""
    return frappe.db.get_value(
        "BOM", {"item": item_code, "is_active": 1, "is_default": 1}, "name"
    ) or frappe.db.get_value("BOM", {"item": item_code, "is_active": 1}, "name")


def _build_bom_node(item_code, qty, visited):
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "stock_uom"],
        as_dict=True,
    ) or {}

    bom_no = _get_bom(item_code)

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

    # BOM Item qty is for the BOM's batch quantity (e.g. per 100), so scale it to 1 unit of the parent
    bom_qty = flt(frappe.db.get_value("BOM", bom_no, "quantity")) or 1

    bom_items = frappe.db.sql("""
        SELECT
            bi.item_code,
            bi.stock_qty AS qty
        FROM `tabBOM Item` bi
        WHERE bi.parent = %s
          AND bi.docstatus < 2
        ORDER BY bi.idx
    """, (bom_no,), as_dict=True)

    for bi in bom_items:
        child_qty = flt(bi.qty) / bom_qty * flt(qty)
        node["children"].append(
            _build_bom_node(bi.item_code, child_qty, visited)
        )

    return node




# ─── Related Documents ────────────────────────────────────────────────────────
# Every non-cancelled document that touches the item, whatever its role in it
# (produced, consumed, supplied to a subcontractor…). Item-wise, not warehouse-wise.
# Each query returns: name, date, status, qty, uom, party, sub_type, ref_doctype, ref_name.

# Party names come from the masters' custom_*_names fields; supplier_name holds the code here.
_STATUS = "CASE WHEN p.docstatus = 0 THEN 'Draft' ELSE p.status END"

_RELATED_QUERIES = [
    ("Material Request", "Item", f"""
        SELECT p.name, p.transaction_date AS date, {_STATUS} AS status,
            SUM(c.stock_qty) AS qty, MAX(c.stock_uom) AS uom, '' AS party, '' AS party_name,
            p.material_request_type AS sub_type,
            IF(MAX(p.work_order) IS NULL, NULL, 'Work Order') AS ref_doctype, MAX(p.work_order) AS ref_name
        FROM `tabMaterial Request Item` c JOIN `tabMaterial Request` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Purchase Order", "Item", f"""
        SELECT p.name, p.transaction_date AS date, {_STATUS} AS status,
            SUM(c.stock_qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name,
            IF(p.is_subcontracted, 'Subcontracted', '') AS sub_type,
            IF(MAX(c.material_request) IS NULL, NULL, 'Material Request') AS ref_doctype, MAX(c.material_request) AS ref_name
        FROM `tabPurchase Order Item` c JOIN `tabPurchase Order` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Purchase Order", "Subcontracted FG", f"""
        SELECT p.name, p.transaction_date AS date, {_STATUS} AS status,
            SUM(c.fg_item_qty) AS qty, '' AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name,
            'Subcontracted' AS sub_type,
            IF(MAX(c.material_request) IS NULL, NULL, 'Material Request') AS ref_doctype, MAX(c.material_request) AS ref_name
        FROM `tabPurchase Order Item` c JOIN `tabPurchase Order` p ON p.name = c.parent
        WHERE c.fg_item = %(item)s AND c.item_code != %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Purchase Receipt", "Item", f"""
        SELECT p.name, p.posting_date AS date, {_STATUS} AS status,
            SUM(c.stock_qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name, '' AS sub_type,
            IF(MAX(c.purchase_order) IS NULL, NULL, 'Purchase Order') AS ref_doctype, MAX(c.purchase_order) AS ref_name
        FROM `tabPurchase Receipt Item` c JOIN `tabPurchase Receipt` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Stock Entry", "Item", """
        SELECT p.name, p.posting_date AS date,
            CASE WHEN p.docstatus = 0 THEN 'Draft' ELSE 'Submitted' END AS status,
            SUM(c.transfer_qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name,
            p.stock_entry_type AS sub_type,
            CASE WHEN p.work_order IS NOT NULL THEN 'Work Order'
                 WHEN p.subcontracting_order IS NOT NULL THEN 'Subcontracting Order'
                 WHEN p.purchase_order IS NOT NULL THEN 'Purchase Order' END AS ref_doctype,
            COALESCE(p.work_order, p.subcontracting_order, p.purchase_order) AS ref_name
        FROM `tabStock Entry Detail` c JOIN `tabStock Entry` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Work Order", "Produces", f"""
        SELECT p.name, p.planned_start_date AS date, {_STATUS} AS status,
            p.qty, p.stock_uom AS uom, '' AS party, '' AS party_name, '' AS sub_type,
            IF(p.production_plan IS NULL, NULL, 'Production Plan') AS ref_doctype, p.production_plan AS ref_name
        FROM `tabWork Order` p
        WHERE p.production_item = %(item)s AND p.docstatus < 2"""),
    ("Work Order", "Consumes (RM)", f"""
        SELECT p.name, p.planned_start_date AS date, {_STATUS} AS status,
            SUM(c.required_qty) AS qty, '' AS uom, '' AS party, '' AS party_name, p.production_item AS sub_type,
            IF(p.production_plan IS NULL, NULL, 'Production Plan') AS ref_doctype, p.production_plan AS ref_name
        FROM `tabWork Order Item` c JOIN `tabWork Order` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Job Card", "Produces", f"""
        SELECT p.name, p.posting_date AS date, {_STATUS} AS status,
            p.for_quantity AS qty, '' AS uom, '' AS party, '' AS party_name, p.operation AS sub_type,
            'Work Order' AS ref_doctype, p.work_order AS ref_name
        FROM `tabJob Card` p
        WHERE p.production_item = %(item)s AND p.docstatus < 2"""),
    ("Subcontracting Order", "Produces", f"""
        SELECT p.name, p.transaction_date AS date, {_STATUS} AS status,
            SUM(c.qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name, '' AS sub_type,
            IF(p.purchase_order IS NULL, NULL, 'Purchase Order') AS ref_doctype, p.purchase_order AS ref_name
        FROM `tabSubcontracting Order Item` c JOIN `tabSubcontracting Order` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Subcontracting Order", "Supplied RM", f"""
        SELECT p.name, p.transaction_date AS date, {_STATUS} AS status,
            SUM(c.required_qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name,
            MAX(c.main_item_code) AS sub_type,
            IF(p.purchase_order IS NULL, NULL, 'Purchase Order') AS ref_doctype, p.purchase_order AS ref_name
        FROM `tabSubcontracting Order Supplied Item` c JOIN `tabSubcontracting Order` p ON p.name = c.parent
        WHERE c.rm_item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Subcontracting Receipt", "Receives", f"""
        SELECT p.name, p.posting_date AS date, {_STATUS} AS status,
            SUM(c.qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name, '' AS sub_type,
            IF(MAX(c.subcontracting_order) IS NULL, NULL, 'Subcontracting Order') AS ref_doctype, MAX(c.subcontracting_order) AS ref_name
        FROM `tabSubcontracting Receipt Item` c JOIN `tabSubcontracting Receipt` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Subcontracting Receipt", "Consumed RM", f"""
        SELECT p.name, p.posting_date AS date, {_STATUS} AS status,
            SUM(c.consumed_qty) AS qty, MAX(c.stock_uom) AS uom, p.supplier AS party, (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = p.supplier) AS party_name,
            MAX(c.main_item_code) AS sub_type, NULL AS ref_doctype, NULL AS ref_name
        FROM `tabSubcontracting Receipt Supplied Item` c JOIN `tabSubcontracting Receipt` p ON p.name = c.parent
        WHERE c.rm_item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Sales Order", "Item", f"""
        SELECT p.name, p.transaction_date AS date, {_STATUS} AS status,
            SUM(c.stock_qty) AS qty, MAX(c.stock_uom) AS uom, p.customer AS party, (SELECT COALESCE(NULLIF(custom_customer_names, ''), customer_name) FROM `tabCustomer` WHERE name = p.customer) AS party_name, '' AS sub_type,
            NULL AS ref_doctype, NULL AS ref_name
        FROM `tabSales Order Item` c JOIN `tabSales Order` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
    ("Delivery Note", "Item", f"""
        SELECT p.name, p.posting_date AS date, {_STATUS} AS status,
            SUM(c.stock_qty) AS qty, MAX(c.stock_uom) AS uom, p.customer AS party, (SELECT COALESCE(NULLIF(custom_customer_names, ''), customer_name) FROM `tabCustomer` WHERE name = p.customer) AS party_name, '' AS sub_type,
            IF(MAX(c.against_sales_order) IS NULL, NULL, 'Sales Order') AS ref_doctype, MAX(c.against_sales_order) AS ref_name
        FROM `tabDelivery Note Item` c JOIN `tabDelivery Note` p ON p.name = c.parent
        WHERE c.item_code = %(item)s AND p.docstatus < 2 GROUP BY p.name"""),
]


@frappe.whitelist()
def get_related_documents(item_code):
    """All non-cancelled documents (drafts included) that involve the item, newest first."""
    if not item_code:
        frappe.throw("Item Code is required")

    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or ""
    docs = []
    for doctype, role, query in _RELATED_QUERIES:
        if not frappe.has_permission(doctype, "read"):
            continue
        for r in frappe.db.sql(query, {"item": item_code}, as_dict=True):
            r.update({
                "doctype": doctype,
                "role": role,
                "date": str(r.date) if r.date else None,
                "qty": flt(r.qty),
                "uom": r.uom or stock_uom,
            })
            docs.append(r)

    docs.sort(key=lambda r: r["date"] or "", reverse=True)
    return docs


# doctype → (MRP-table icon, direction per role); None = no fixed direction
_RELATED_ICON = {
    "Purchase Order": "po", "Purchase Receipt": "grn", "Subcontracting Order": "sco",
    "Subcontracting Receipt": "scr", "Work Order": "wo", "Job Card": "jc",
    "Stock Entry": "se", "Sales Order": "so", "Delivery Note": "dn",
}
_REQUIREMENT_ROLES = {"Consumes (RM)", "Supplied RM", "Consumed RM"}
_REQUIREMENT_DOCTYPES = {"Sales Order", "Delivery Note"}


def _related_to_row(d):
    if d["doctype"] == "Material Request":
        icon = "pr" if d.sub_type == "Purchase" else "mr"
        direction = "receipt" if d.sub_type == "Purchase" else None
    else:
        icon = _RELATED_ICON.get(d["doctype"], "")
        if d.role in _REQUIREMENT_ROLES or d["doctype"] in _REQUIREMENT_DOCTYPES:
            direction = "requirement"
        elif d["doctype"] == "Stock Entry":
            direction = None
        else:
            direction = "receipt"

    return {
        "document_type": d["doctype"],
        "doctype": d["doctype"],
        "document_name": d["name"],
        "date": d["date"],
        "qty": -d["qty"] if direction == "requirement" else d["qty"],
        "uom": d["uom"],
        "party": d.party or "",
        "party_name": d.party_name or "",
        "status": d.status,
        "direction": direction,
        "icon": icon,
        "sub_type": d.role if d.role != "Item" else d.sub_type,
        "ref_doctype": d.ref_doctype,
        "ref_name": d.ref_name,
        "available_qty": None,
        "in_mrp": 0,
    }


def _get_actual_stock(item_code, warehouse):
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(actual_qty), 0)
        FROM `tabBin`
        WHERE item_code = %s AND (%s = '' OR warehouse = %s)
    """, (item_code, warehouse, warehouse))
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
            (SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = po.supplier) AS party_name,
            po.status
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE poi.item_code = %s
          AND (%s = '' OR poi.warehouse = %s)
          AND po.docstatus = 1
          AND po.status NOT IN ('Completed', 'Cancelled', 'Closed')
          AND (poi.qty - poi.received_qty) > 0
    """, (item_code, warehouse, warehouse), as_dict=True)

    return [
        {
            "document_type": "Purchase Order",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": flt(r.qty),
            "uom": r.uom,
            "rate": flt(r.rate),
            "party": r.party,
            "party_name": r.party_name,
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
            mr.docstatus,
            mr.status
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE mri.item_code = %s
          AND (%s = '' OR mri.warehouse = %s)
          AND mr.docstatus IN (0, 1)
          AND mr.material_request_type = 'Purchase'
          AND mr.status NOT IN ('Ordered', 'Cancelled', 'Stopped')
    """, (item_code, warehouse, warehouse), as_dict=True)

    return [
        {
            "document_type": "Purchase Requisition",
            "doctype": "Material Request",  # PR is a label; the actual document is a Material Request
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": flt(r.qty),
            "uom": r.uom,
            "rate": 0,
            "party": "",
            "status": r.status if r.docstatus == 1 else "Draft",
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
          AND (%s = '' OR wo.fg_warehouse = %s)
          AND wo.docstatus = 1
          AND wo.status NOT IN ('Completed', 'Cancelled', 'Stopped')
          AND (wo.qty - wo.produced_qty) > 0
    """, (item_code, warehouse, warehouse), as_dict=True)

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
    """Draft stock entries that will add stock (Material Receipt / Material Transfer In).
    Across all warehouses a transfer just moves stock around, so it is skipped then."""
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
          AND (%s = '' OR sed.t_warehouse = %s)
          AND se.docstatus = 0
          AND se.stock_entry_type IN ('Material Receipt', 'Material Transfer', 'Manufacture')
          AND NOT (%s = '' AND se.stock_entry_type = 'Material Transfer')
    """, (item_code, warehouse, warehouse, warehouse), as_dict=True)

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
          AND (%s = '' OR soi.warehouse = %s)
          AND so.docstatus = 1
          AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
          AND (soi.qty - soi.delivered_qty) > 0
    """, (item_code, warehouse, warehouse), as_dict=True)

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
            mr.docstatus,
            mr.status
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE mri.item_code = %s
          AND (%s = '' OR mri.warehouse = %s)
          AND mr.docstatus IN (0, 1)
          AND mr.material_request_type = 'Material Issue'
          AND mr.status NOT IN ('Transferred', 'Issued', 'Cancelled', 'Stopped')
    """, (item_code, warehouse, warehouse), as_dict=True)

    return [
        {
            "document_type": "Material Request",
            "document_name": r.document_name,
            "date": str(r.date) if r.date else None,
            "qty": -flt(r.qty),
            "uom": r.uom,
            "rate": 0,
            "party": "",
            "status": r.status if r.docstatus == 1 else "Draft",
            "direction": "requirement",
            "icon": "mr",
        }
        for r in rows
    ]