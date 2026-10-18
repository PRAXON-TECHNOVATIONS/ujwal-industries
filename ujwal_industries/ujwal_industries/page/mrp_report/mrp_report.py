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
    rows += _get_mrp_elements(item_code, warehouse)

    for_items = {r["for_item"] for r in rows if r.get("for_item")}
    if for_items:
        names = dict(frappe.get_all("Item", {"name": ("in", list(for_items))}, ["name", "item_name"], as_list=True))
        for r in rows:
            if r.get("for_item"):
                r["for_item_name"] = names.get(r["for_item"], "")

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
        r["qty"] = flt(r.get("qty", 0), 6)
        running = flt(running + r["qty"], 6)
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

    # Root shows its BOM's quantity; every child shows its BOM Item qty as is
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


def _build_bom_node(item_code, qty, visited, uom=None):
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
        "uom": uom or item.get("stock_uom", ""),
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
            bi.qty,
            bi.uom
        FROM `tabBOM Item` bi
        WHERE bi.parent = %s
          AND bi.docstatus < 2
        ORDER BY bi.idx
    """, (bom_no,), as_dict=True)

    # Qty exactly as written in the BOM, not scaled to the parent
    for bi in bom_items:
        node["children"].append(
            _build_bom_node(bi.item_code, flt(bi.qty), visited, uom=bi.uom)
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
            IF(MAX(p.work_order) IS NULL, NULL, 'Work Order') AS ref_doctype, MAX(p.work_order) AS ref_name,
            (SELECT production_item FROM `tabWork Order` WHERE name = MAX(p.work_order)) AS for_item
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
            COALESCE(p.work_order, p.subcontracting_order, p.purchase_order) AS ref_name,
            (SELECT production_item FROM `tabWork Order` WHERE name = p.work_order) AS for_item
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
            SUM(c.required_qty) AS qty, '' AS uom, '' AS party, '' AS party_name, '' AS sub_type, p.production_item AS for_item,
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
            '' AS sub_type, MAX(c.main_item_code) AS for_item,
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
            '' AS sub_type, MAX(c.main_item_code) AS for_item, NULL AS ref_doctype, NULL AS ref_name
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

    # "For Item": the parent item the document consumes/supplies this item for
    for_items = {r.get("for_item") for r in docs if r.get("for_item") and r.get("for_item") != item_code}
    names = dict(frappe.get_all("Item", {"name": ("in", list(for_items))}, ["name", "item_name"], as_list=True)) if for_items else {}
    for r in docs:
        fi = r.get("for_item")
        r["for_item"] = fi if fi and fi != item_code else None
        r["for_item_name"] = names.get(fi, "") if r["for_item"] else ""

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
        "for_item": d.for_item,
        "for_item_name": d.for_item_name,
        # consumption rows are read-only: act on them from the parent (FG) item
        "read_only": 1 if d.role in _REQUIREMENT_ROLES else 0,
        "available_qty": None,
        "in_mrp": 0,
    }


def get_available_qty(item_code, warehouse):
    """End balance of the Stock/Requirements list: stock + every open receipt
    − every open requirement, drafts included. Bulk PP nets planning against it."""
    return flt(_get_actual_stock(item_code, warehouse)) + sum(
        flt(r["qty"]) for r in _get_mrp_elements(item_code, warehouse)
    )


def _get_mrp_elements(item_code, warehouse):
    return (
        _get_purchase_orders(item_code, warehouse)
        + _get_subcontracted_po_receipts(item_code, warehouse)
        + _get_material_request_receipts(item_code, warehouse)
        + _get_work_orders_receipt(item_code, warehouse)
        + _get_subcontracting_receipts(item_code, warehouse)
        + _get_stock_entries(item_code, warehouse)
        + _get_sales_orders(item_code, warehouse)
        + _get_work_order_requirements(item_code, warehouse)
        + _get_subcontracting_requirements(item_code, warehouse)
        + _get_material_request_requirements(item_code, warehouse)
    )


def _get_actual_stock(item_code, warehouse):
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(actual_qty), 0)
        FROM `tabBin`
        WHERE item_code = %s AND (%s = '' OR warehouse = %s)
    """, (item_code, warehouse, warehouse))
    return flt(result[0][0]) if result else 0.0


# ─── MRP elements ─────────────────────────────────────────────────────────────
# Every open quantity that will move the item's stock, like SAP MD04:
#   receipts:     PO (drafts too), subcontracted PO FG until its SCO exists, Purchase / Customer Provided / Manufacture MR, Work Order
#                 (submitted = production order, draft = planned order),
#                 Subcontracting Order FG, draft Stock Entry, Transfer MR (in)
#   requirements: Sales Order, Work Order RM (submitted = reservation,
#                 draft = dependent requirement), Subcontracting supplied RM,
#                 Issue MR, draft Stock Entry, Transfer MR (out)
# All quantities are open quantities in the stock UOM.
# Drafts that would double count an already-counted document (draft GRN/DN
# against a PO/SO, draft Stock Entry of a WO/SCO) are skipped; a draft PO made
# from an MR is taken off the MR's open qty instead.

_SUPPLIER_NAME = "(SELECT COALESCE(NULLIF(custom_supplier_names, ''), supplier_name) FROM `tabSupplier` WHERE name = {0})"
_CUSTOMER_NAME = "(SELECT COALESCE(NULLIF(custom_customer_names, ''), customer_name) FROM `tabCustomer` WHERE name = {0})"


def _mrp_row(r, doctype, direction, icon, **extra):
    qty = flt(r.qty)
    row = {
        "document_type": doctype,
        "doctype": doctype,
        "document_name": r.document_name,
        "date": str(r.date)[:10] if r.date else None,
        "qty": -qty if direction == "requirement" else qty,
        "uom": r.get("uom") or "",
        "party": r.get("party") or "",
        "party_name": r.get("party_name") or "",
        "status": "Draft" if r.get("docstatus") == 0 else r.get("status"),
        "direction": direction,
        "icon": icon,
        "sub_type": r.get("sub_type") or "",
        "ref_doctype": r.get("ref_doctype"),
        "ref_name": r.get("ref_name"),
        "for_item": r.get("for_item"),
        "for_item_name": "",
        "warehouse": r.get("warehouse") or "",
        "read_only": 0,
    }
    row.update(extra)
    return row


# ─── Receipts ─────────────────────────────────────────────────────────────────

def _get_purchase_orders(item_code, warehouse):
    """Open PO lines, drafts included (like an unreleased PO in SAP)."""
    rows = frappe.db.sql(f"""
        SELECT
            poi.parent          AS document_name,
            poi.schedule_date   AS date,
            (poi.qty - poi.received_qty) * poi.conversion_factor AS qty,
            poi.stock_uom       AS uom,
            poi.warehouse,
            po.supplier         AS party,
            {_SUPPLIER_NAME.format("po.supplier")} AS party_name,
            po.docstatus, po.status,
            IF(poi.material_request IS NULL, NULL, 'Material Request') AS ref_doctype,
            poi.material_request AS ref_name
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE poi.item_code = %(item)s
          AND (%(wh)s = '' OR poi.warehouse = %(wh)s)
          AND (po.docstatus = 0
               OR (po.docstatus = 1 AND po.status NOT IN ('Completed', 'Closed', 'Delivered')))
          AND po.is_subcontracted = 0
          AND poi.delivered_by_supplier = 0
          AND poi.qty > poi.received_qty
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Purchase Order", "receipt", "po") for r in rows]


def _get_subcontracted_po_receipts(item_code, warehouse):
    """FG of a subcontracted PO (drafts included) that has no Subcontracting
    Order yet; once the SCO exists the FG is counted through the SCO."""
    rows = frappe.db.sql(f"""
        SELECT
            poi.parent          AS document_name,
            poi.schedule_date   AS date,
            poi.fg_item_qty     AS qty,
            (SELECT stock_uom FROM `tabItem` WHERE name = poi.fg_item) AS uom,
            poi.warehouse,
            po.supplier         AS party,
            {_SUPPLIER_NAME.format("po.supplier")} AS party_name,
            po.docstatus, po.status,
            'Subcontracted FG'  AS sub_type,
            IF(poi.material_request IS NULL, NULL, 'Material Request') AS ref_doctype,
            poi.material_request AS ref_name
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE poi.fg_item = %(item)s
          AND (%(wh)s = '' OR poi.warehouse = %(wh)s)
          AND (po.docstatus = 0
               OR (po.docstatus = 1 AND po.status NOT IN ('Completed', 'Closed', 'Delivered')))
          AND po.is_subcontracted = 1
          AND NOT EXISTS (SELECT 1 FROM `tabSubcontracting Order` sco
                          WHERE sco.purchase_order = po.name AND sco.docstatus < 2)
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Purchase Order", "receipt", "po") for r in rows if flt(r.qty) > 0]


def _get_material_request_receipts(item_code, warehouse):
    """Purchase / Customer Provided / Manufacture MRs (drafts too) for their
    open qty, plus the incoming side of a Material Transfer MR when a
    warehouse is selected (across all warehouses a transfer nets to zero)."""
    rows = frappe.db.sql("""
        SELECT
            mri.parent          AS document_name,
            mri.schedule_date   AS date,
            mri.stock_qty - IF(mr.material_request_type = 'Customer Provided',
                               mri.received_qty, mri.ordered_qty)
                - IF(mr.material_request_type = 'Purchase', (
                    SELECT COALESCE(SUM(IF(po.is_subcontracted, poi.fg_item_qty, poi.stock_qty)), 0)
                    FROM `tabPurchase Order Item` poi
                    JOIN `tabPurchase Order` po ON po.name = poi.parent
                    WHERE poi.material_request_item = mri.name AND po.docstatus = 0
                  ), 0) AS qty,
            mri.stock_uom       AS uom,
            mri.warehouse,
            mr.docstatus, mr.status,
            mr.material_request_type AS sub_type,
            IF(mr.work_order IS NULL, NULL, 'Work Order') AS ref_doctype,
            mr.work_order       AS ref_name
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE mri.item_code = %(item)s
          AND (%(wh)s = '' OR mri.warehouse = %(wh)s)
          AND mr.docstatus < 2
          AND mr.status NOT IN ('Stopped', 'Cancelled')
          AND (mr.material_request_type IN ('Purchase', 'Customer Provided', 'Manufacture')
               OR (%(wh)s != '' AND mr.material_request_type = 'Material Transfer'
                   AND COALESCE(NULLIF(mri.from_warehouse, ''), mr.set_from_warehouse, '') != %(wh)s))
    """, {"item": item_code, "wh": warehouse}, as_dict=True)

    out = []
    for r in rows:
        if flt(r.qty) <= 0:
            continue
        if r.sub_type == "Purchase":
            out.append(_mrp_row(r, "Material Request", "receipt", "pr", document_type="Purchase Requisition"))
        else:
            out.append(_mrp_row(r, "Material Request", "receipt", "mr"))
    return out


def _get_work_orders_receipt(item_code, warehouse):
    """Submitted WO = production order (qty still to produce);
    draft WO = planned order (full qty)."""
    rows = frappe.db.sql("""
        SELECT
            wo.name             AS document_name,
            COALESCE(wo.planned_end_date, wo.expected_delivery_date, wo.planned_start_date) AS date,
            IF(wo.docstatus = 0, wo.qty, wo.qty - wo.produced_qty) AS qty,
            wo.stock_uom        AS uom,
            wo.fg_warehouse     AS warehouse,
            wo.docstatus, wo.status,
            'Produces'          AS sub_type,
            IF(wo.production_plan IS NULL, NULL, 'Production Plan') AS ref_doctype,
            wo.production_plan  AS ref_name
        FROM `tabWork Order` wo
        WHERE wo.production_item = %(item)s
          AND (%(wh)s = '' OR wo.fg_warehouse = %(wh)s)
          AND wo.docstatus < 2
          AND wo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Work Order", "receipt", "wo") for r in rows if flt(r.qty) > 0]


def _get_subcontracting_receipts(item_code, warehouse):
    rows = frappe.db.sql(f"""
        SELECT
            scoi.parent         AS document_name,
            scoi.schedule_date  AS date,
            (scoi.qty - scoi.received_qty) * scoi.conversion_factor AS qty,
            scoi.stock_uom      AS uom,
            scoi.warehouse,
            sco.supplier        AS party,
            {_SUPPLIER_NAME.format("sco.supplier")} AS party_name,
            sco.docstatus, sco.status,
            'Produces'          AS sub_type,
            IF(sco.purchase_order IS NULL, NULL, 'Purchase Order') AS ref_doctype,
            sco.purchase_order  AS ref_name
        FROM `tabSubcontracting Order Item` scoi
        JOIN `tabSubcontracting Order` sco ON sco.name = scoi.parent
        WHERE scoi.item_code = %(item)s
          AND (%(wh)s = '' OR scoi.warehouse = %(wh)s)
          AND sco.docstatus < 2
          AND sco.status NOT IN ('Completed', 'Closed', 'Cancelled')
          AND scoi.qty > scoi.received_qty
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Subcontracting Order", "receipt", "sco") for r in rows]


def _get_stock_entries(item_code, warehouse):
    """Draft Stock Entries not linked to a WO / SCO (those are already counted
    through the order). A row that only puts stock in is a receipt, one that
    only takes stock out a requirement; with a warehouse selected, transfers
    into / out of it count too."""
    rows = frappe.db.sql("""
        SELECT
            sed.parent          AS document_name,
            se.posting_date     AS date,
            sed.transfer_qty    AS qty,
            sed.stock_uom       AS uom,
            sed.s_warehouse, sed.t_warehouse,
            se.docstatus,
            se.stock_entry_type AS sub_type
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE sed.item_code = %(item)s
          AND se.docstatus = 0
          AND se.work_order IS NULL
          AND se.subcontracting_order IS NULL
          AND COALESCE(se.purchase_order, '') = ''
    """, {"item": item_code}, as_dict=True)

    out = []
    for r in rows:
        s, t = r.s_warehouse or "", r.t_warehouse or ""
        if warehouse:
            if t == warehouse and s != warehouse:
                out.append(_mrp_row(r, "Stock Entry", "receipt", "se", warehouse=t))
            elif s == warehouse and t != warehouse:
                out.append(_mrp_row(r, "Stock Entry", "requirement", "se", warehouse=s))
        elif t and not s:
            out.append(_mrp_row(r, "Stock Entry", "receipt", "se", warehouse=t))
        elif s and not t:
            out.append(_mrp_row(r, "Stock Entry", "requirement", "se", warehouse=s))
    return out


# ─── Requirements ─────────────────────────────────────────────────────────────

def _get_sales_orders(item_code, warehouse):
    rows = frappe.db.sql(f"""
        SELECT
            soi.parent          AS document_name,
            COALESCE(soi.delivery_date, so.delivery_date) AS date,
            (soi.qty - soi.delivered_qty) * soi.conversion_factor AS qty,
            soi.stock_uom       AS uom,
            soi.warehouse,
            so.customer         AS party,
            {_CUSTOMER_NAME.format("so.customer")} AS party_name,
            so.docstatus, so.status
        FROM `tabSales Order Item` soi
        JOIN `tabSales Order` so ON so.name = soi.parent
        WHERE soi.item_code = %(item)s
          AND (%(wh)s = '' OR soi.warehouse = %(wh)s)
          AND so.docstatus = 1
          AND so.status NOT IN ('Completed', 'Closed')
          AND soi.delivered_by_supplier = 0
          AND soi.qty > soi.delivered_qty
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Sales Order", "requirement", "so") for r in rows]


def _get_work_order_requirements(item_code, warehouse):
    """RM of a Work Order. Draft WO = dependent requirement (full required qty);
    submitted WO = reservation, open until consumed. With a warehouse selected,
    material already transferred out of it (to WIP) is no longer required there."""
    rows = frappe.db.sql("""
        SELECT
            wo.name             AS document_name,
            wo.planned_start_date AS date,
            SUM(CASE
                WHEN wo.docstatus = 0 THEN woi.required_qty
                WHEN %(wh)s = '' THEN woi.required_qty - woi.consumed_qty
                ELSE woi.required_qty - GREATEST(woi.transferred_qty - woi.returned_qty, woi.consumed_qty)
            END)                AS qty,
            MAX(woi.stock_uom)  AS uom,
            MAX(woi.source_warehouse) AS warehouse,
            wo.docstatus, wo.status,
            'Consumes (RM)'     AS sub_type,
            wo.production_item  AS for_item,
            IF(wo.production_plan IS NULL, NULL, 'Production Plan') AS ref_doctype,
            wo.production_plan  AS ref_name
        FROM `tabWork Order Item` woi
        JOIN `tabWork Order` wo ON wo.name = woi.parent
        WHERE woi.item_code = %(item)s
          AND (%(wh)s = '' OR woi.source_warehouse = %(wh)s)
          AND wo.docstatus < 2
          AND wo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
        GROUP BY wo.name
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Work Order", "requirement", "wo", read_only=1) for r in rows if flt(r.qty) > 0]


def _get_subcontracting_requirements(item_code, warehouse):
    """RM to supply to the subcontractor, open until consumed in a
    Subcontracting Receipt (stock sent to the supplier warehouse is still ours).
    With a warehouse selected, material already sent out of it is no longer required there."""
    rows = frappe.db.sql(f"""
        SELECT
            sco.name            AS document_name,
            sco.schedule_date   AS date,
            SUM(CASE
                WHEN %(wh)s = '' THEN sosi.required_qty - sosi.consumed_qty
                ELSE sosi.required_qty - GREATEST(sosi.supplied_qty - sosi.returned_qty, sosi.consumed_qty)
            END)                AS qty,
            MAX(sosi.stock_uom) AS uom,
            MAX(sosi.reserve_warehouse) AS warehouse,
            sco.supplier        AS party,
            {_SUPPLIER_NAME.format("sco.supplier")} AS party_name,
            sco.docstatus, sco.status,
            'Supplied RM'       AS sub_type,
            MAX(sosi.main_item_code) AS for_item,
            IF(sco.purchase_order IS NULL, NULL, 'Purchase Order') AS ref_doctype,
            sco.purchase_order  AS ref_name
        FROM `tabSubcontracting Order Supplied Item` sosi
        JOIN `tabSubcontracting Order` sco ON sco.name = sosi.parent
        WHERE sosi.rm_item_code = %(item)s
          AND (%(wh)s = '' OR sosi.reserve_warehouse = %(wh)s)
          AND sco.docstatus < 2
          AND sco.status NOT IN ('Completed', 'Closed', 'Cancelled')
        GROUP BY sco.name
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Subcontracting Order", "requirement", "sco", read_only=1) for r in rows if flt(r.qty) > 0]


def _get_material_request_requirements(item_code, warehouse):
    """Material Issue MRs (drafts too) for the qty not yet issued, plus the
    outgoing side of a Material Transfer MR when a warehouse is selected."""
    rows = frappe.db.sql("""
        SELECT
            mri.parent          AS document_name,
            mri.schedule_date   AS date,
            mri.stock_qty - mri.ordered_qty AS qty,
            mri.stock_uom       AS uom,
            IF(mr.material_request_type = 'Material Transfer',
               COALESCE(NULLIF(mri.from_warehouse, ''), mr.set_from_warehouse), mri.warehouse) AS warehouse,
            mr.docstatus, mr.status,
            mr.material_request_type AS sub_type,
            IF(mr.work_order IS NULL, NULL, 'Work Order') AS ref_doctype,
            mr.work_order       AS ref_name
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE mri.item_code = %(item)s
          AND mr.docstatus < 2
          AND mr.status NOT IN ('Stopped', 'Cancelled')
          AND ((mr.material_request_type = 'Material Issue' AND (%(wh)s = '' OR mri.warehouse = %(wh)s))
               OR (%(wh)s != '' AND mr.material_request_type = 'Material Transfer'
                   AND COALESCE(NULLIF(mri.from_warehouse, ''), mr.set_from_warehouse) = %(wh)s
                   AND mri.warehouse != %(wh)s))
    """, {"item": item_code, "wh": warehouse}, as_dict=True)
    return [_mrp_row(r, "Material Request", "requirement", "mr") for r in rows if flt(r.qty) > 0]
