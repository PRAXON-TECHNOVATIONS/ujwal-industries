
import frappe


def before_insert(doc, method):
    if doc.amended_from:
        if frappe.db.exists("Sales Order", doc.amended_from):
            frappe.delete_doc("Sales Order", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None
        
        
        

def autoname(doc, method):
    invoice_type = None
    if doc.get("is_subcontracted"):
        invoice_type = "Sub Con PO"

    elif doc.get("custom_service_po"):
        invoice_type = "Service PO"
        
    elif doc.get("custom_purchase_type") == "Import RM":
        invoice_type = "Import RM PO"
        
    elif doc.get("custom_purchase_type") == "Local":
        invoice_type = ""     

    if invoice_type is None:
        return

    settings = frappe.get_doc("Document Series Settings")
    for row in settings.document_series:

        if (
            row.document_type == "Purchase Order"
            and row.type == invoice_type
        ):

            start_number = int(row.start_number)
            end_number = int(row.end_number)

            if not row.current_number:
                new_number = start_number
            else:
                new_number = int(row.current_number) + 1

            if new_number > end_number:
                frappe.throw(f"{invoice_type} series limit exceeded")

            doc.name = str(new_number)
            frappe.db.set_value(row.doctype , row.name, "current_number", new_number)
            break        

# PO categories, keyed by the PO Visibility Rule checkbox that allows them.
# Subcontracted wins over Service when both flags are ticked.
PO_CATEGORY_CONDITIONS = {
    "show_normal": "ifnull({t}.`is_subcontracted`, 0) = 0 and ifnull({t}.`custom_service_po`, 0) = 0",
    "show_service": "ifnull({t}.`is_subcontracted`, 0) = 0 and ifnull({t}.`custom_service_po`, 0) = 1",
    "show_subcontracted": "ifnull({t}.`is_subcontracted`, 0) = 1",
}


def _get_allowed_po_categories(user: str) -> set[str] | None:
    """Return the PO categories the user may see, or None for no restriction.

    Driven by Ujwal Industries Setting > PO Visibility Rules. Administrator,
    System Manager and users with none of the listed roles are unrestricted;
    a user with several listed roles gets the union of their categories.
    """
    if user == "Administrator":
        return None

    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return None

    rules = [
        rule
        for rule in frappe.get_cached_doc("Ujwal Industries Setting").get("po_visibility_rules") or []
        if rule.role in roles
    ]
    if not rules:
        return None

    allowed = {key for key in PO_CATEGORY_CONDITIONS for rule in rules if rule.get(key)}
    if allowed == set(PO_CATEGORY_CONDITIONS):
        return None

    return allowed


def _get_po_category(doc) -> str:
    if doc.get("is_subcontracted"):
        return "show_subcontracted"
    if doc.get("custom_service_po"):
        return "show_service"
    return "show_normal"


def _get_po_condition(allowed: set[str], table: str = "`tabPurchase Order`") -> str:
    if not allowed:
        return "1=0"

    return " or ".join(f"({PO_CATEGORY_CONDITIONS[key].format(t=table)})" for key in sorted(allowed))


def has_permission_query_purchase_order(user: str) -> str | None:
    allowed = _get_allowed_po_categories(user)
    if allowed is None:
        return None

    return f"({_get_po_condition(allowed)})"


def has_permission_purchase_order(doc, ptype: str, user: str, debug: bool = False) -> bool | None:
    allowed = _get_allowed_po_categories(user)
    if allowed is None or ptype == "create":
        return None

    return _get_po_category(doc) in allowed


def filter_rows_by_po_access(rows, po_field="purchase_order", user=None):
    """Drop report rows whose Purchase Order the user isn't allowed to see."""
    allowed = _get_allowed_po_categories(user or frappe.session.user)
    if allowed is None or not rows:
        return rows

    po_names = {row.get(po_field) for row in rows if row.get(po_field)}
    visible = set(
        frappe.db.sql_list(
            f"""select name from `tabPurchase Order`
            where name in %(names)s and ({_get_po_condition(allowed)})""",
            {"names": tuple(po_names)},
        )
    ) if po_names else set()

    return [row for row in rows if row.get(po_field) in visible]
