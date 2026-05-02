import frappe


def _plain_count(value):
    return str(int(value or 0))


def _production_plan_card_response(value, status):
    return {
        "value": _plain_count(value),
        "fieldtype": "Data",
        "route": ["List", "Production Plan"],
        "route_options": {
            "Production Plan.docstatus": ["<", 2],
            "Production Plan.status": ["=", status],
        },
    }


@frappe.whitelist()
def get_bulk_pre_production_count():
    value = len(
        frappe.get_all(
            "Bulk PP Sales Order",
            filters={
                "parenttype": "Bulk Pre Production Plan",
                "sales_order": ["is", "set"],
            },
            fields=["parent"],
            group_by="parent",
        )
    )

    return {
        "value": _plain_count(value),
        "fieldtype": "Data",
        "route": ["List", "Bulk Pre Production Plan"],
        "route_options": {
            "Bulk Pre Production Plan.docstatus": ["<", 2],
        },
    }


@frappe.whitelist()
def get_bulk_linked_production_plan_count():
    value = frappe.db.count(
        "Production Plan",
        {
            "docstatus": ["<", 2],
            "custom_bulk_pre_production_plan": ["is", "set"],
        },
    )

    return {
        "value": _plain_count(value),
        "fieldtype": "Data",
        "route": ["List", "Production Plan"],
        "route_options": {
            "Production Plan.docstatus": ["<", 2],
            "Production Plan.custom_bulk_pre_production_plan": ["is", "set"],
        },
    }


@frappe.whitelist()
def get_not_started_production_plan_count():
    value = frappe.db.count(
        "Production Plan",
        {
            "docstatus": ["<", 2],
            "status": "Submitted",
        },
    )
    return _production_plan_card_response(value, "Submitted")


@frappe.whitelist()
def get_completed_production_plan_count():
    value = frappe.db.count(
        "Production Plan",
        {
            "docstatus": ["<", 2],
            "status": "Completed",
        },
    )
    return _production_plan_card_response(value, "Completed")
