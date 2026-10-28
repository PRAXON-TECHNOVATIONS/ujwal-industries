
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


# ---------------------------------------------------------------------------
# Submission tracking — system-generated POs (from Bulk PP / Production Plan)
# are created as drafts. Record when they were generated and when / by whom
# they were submitted, and date the PO on its submit day so the delay shows.
# ---------------------------------------------------------------------------

def _is_system_generated(doc) -> bool:
    return any(row.get("production_plan") for row in doc.get("items") or [])


def set_generated_on(doc, method=None):
    """before_insert: stamp when the system created this PO."""
    if _is_system_generated(doc) and not doc.get("custom_generated_on"):
        doc.custom_generated_on = frappe.utils.now_datetime()


def validate_po_type(doc, method=None):
    """A PO is either Subcontracted or Service, never both."""
    if doc.get("is_subcontracted") and doc.get("custom_service_po"):
        frappe.throw(
            frappe._("A Purchase Order can be either Subcontracted or Service PO, not both. Please untick one."),
            title=frappe._("Conflicting PO Type"),
        )


def date_po_on_submit(doc, method=None):
    """
    before_validate on submit: PO date becomes the submit date (ERPNext's own date checks
    then run against it), payment-schedule due dates move by the same number of days,
    and Submitted On / By / Delay are recorded. Blocks when a Required By date has already
    passed — the buyer should agree a new date with the supplier first.
    """
    from frappe.utils import add_days, date_diff, getdate, now_datetime, time_diff_in_hours

    if doc._action != "submit" or not _is_system_generated(doc):
        return

    submitted_on = now_datetime()
    today = submitted_on.date()

    late_rows = [
        frappe._("Row {0}: <b>{1}</b> — Required By {2}").format(
            row.idx, row.item_code, frappe.format_value(row.schedule_date, {"fieldtype": "Date"})
        )
        for row in doc.items
        if row.schedule_date and getdate(row.schedule_date) < today
    ]
    if late_rows:
        frappe.throw(
            frappe._(
                "The Required By date has already passed for these items:<br><br>{0}<br><br>"
                "Agree a new Required By date with the supplier, update the rows, then submit."
            ).format("<br>".join(late_rows)),
            title=frappe._("Required By Date Passed"),
        )

    shift_days = date_diff(today, doc.transaction_date)
    if shift_days:
        doc.transaction_date = today
        for row in doc.get("payment_schedule") or []:
            if row.due_date:
                row.due_date = add_days(row.due_date, shift_days)
            if row.get("discount_date"):
                row.discount_date = add_days(row.discount_date, shift_days)

    doc.custom_generated_on = doc.get("custom_generated_on") or doc.creation
    doc.custom_submitted_on = submitted_on
    doc.custom_submitted_by = frappe.session.user
    doc.custom_submission_delay_days = round(
        max(time_diff_in_hours(submitted_on, doc.custom_generated_on), 0) / 24, 1
    )
