"""
Optimized Auto Reorder System for JMT
- Hourly execution instead of daily
- Cumulative Material Requests (grouped by warehouse)
- Warehouse hierarchy caching for performance
- Reduced execution time
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate
from typing import Dict, List
import erpnext


# Warehouse hierarchy cache (refreshed hourly)
_warehouse_cache = {}


def optimized_reorder_item():
    """
    Optimized reorder item function
    - Caches warehouse hierarchy
    - Creates cumulative MRs
    - Faster execution
    """
    # Check if auto_indent is enabled
    if not cint(frappe.db.get_value("Stock Settings", None, "auto_indent")):
        return

    # Clear warehouse cache at the start of each run
    global _warehouse_cache
    _warehouse_cache = {}

    return _execute_optimized_reorder()


def _execute_optimized_reorder():
    """Execute the optimized reorder logic"""

    # Dictionary to store material requests grouped by (company, warehouse, mr_type)
    material_requests = {}

    warehouse_company = frappe._dict(
        frappe.db.sql(
            """select name, company from `tabWarehouse`
            where disabled=0"""
        )
    )

    default_company = (
        erpnext.get_default_company()
        or frappe.db.sql("""select name from tabCompany limit 1""")[0][0]
    )

    # Get items that need reordering
    items_to_consider = get_items_for_reorder_optimized()

    if not items_to_consider:
        return

    # Get projected quantities with optimized query
    item_warehouse_projected_qty = get_item_warehouse_projected_qty_optimized(
        items_to_consider
    )

    # Process each item and add to material request groups
    for item_code, reorder_levels in items_to_consider.items():
        for d in reorder_levels:
            if d.has_variants:
                continue

            process_item_for_reorder(
                item_code=item_code,
                item_data=d,
                item_warehouse_projected_qty=item_warehouse_projected_qty,
                warehouse_company=warehouse_company,
                default_company=default_company,
                material_requests=material_requests,
            )

    if material_requests:
        return create_cumulative_material_requests(material_requests)


def get_items_for_reorder_optimized() -> dict:
    """
    Get items for reorder with optimized query
    - Single query instead of multiple
    - Only fetch required fields
    """
    reorder_table = frappe.qb.DocType("Item Reorder")
    item_table = frappe.qb.DocType("Item")

    query = (
        frappe.qb.from_(reorder_table)
        .inner_join(item_table)
        .on(reorder_table.parent == item_table.name)
        .select(
            reorder_table.warehouse,
            reorder_table.warehouse_group,
            reorder_table.material_request_type,
            reorder_table.warehouse_reorder_level,
            reorder_table.warehouse_reorder_qty,
            item_table.name,
            item_table.stock_uom,
            item_table.purchase_uom,
            item_table.description,
            item_table.item_name,
            item_table.item_group,
            item_table.brand,
            item_table.variant_of,
            item_table.has_variants,
            item_table.lead_time_days,
        )
        .where(
            (item_table.disabled == 0)
            & (item_table.is_stock_item == 1)
            & (
                (item_table.end_of_life.isnull())
                | (item_table.end_of_life > nowdate())
                | (item_table.end_of_life == "0000-00-00")
            )
        )
    )

    data = query.run(as_dict=True)
    itemwise_reorder = frappe._dict({})
    for d in data:
        itemwise_reorder.setdefault(d.name, []).append(d)

    # Handle variants
    itemwise_reorder = get_reorder_levels_for_variants(itemwise_reorder)

    return itemwise_reorder


def get_reorder_levels_for_variants(itemwise_reorder):
    """Get reorder levels for variant items"""
    item_table = frappe.qb.DocType("Item")

    query = (
        frappe.qb.from_(item_table)
        .select(
            item_table.name,
            item_table.variant_of,
        )
        .where(
            (item_table.disabled == 0)
            & (item_table.is_stock_item == 1)
            & (
                (item_table.end_of_life.isnull())
                | (item_table.end_of_life > nowdate())
                | (item_table.end_of_life == "0000-00-00")
            )
            & (item_table.variant_of.notnull())
        )
    )

    variants_item = query.run(as_dict=True)
    for row in variants_item:
        if not itemwise_reorder.get(row.name) and itemwise_reorder.get(row.variant_of):
            itemwise_reorder.setdefault(row.name, []).extend(
                itemwise_reorder.get(row.variant_of, [])
            )

    return itemwise_reorder


def get_item_warehouse_projected_qty_optimized(items_to_consider):
    """
    Optimized version with warehouse hierarchy caching
    - Builds warehouse hierarchy cache once
    - Reduces N+1 queries to single query
    """
    item_warehouse_projected_qty = {}
    items_to_consider = list(items_to_consider.keys())

    if not items_to_consider:
        return item_warehouse_projected_qty

    # Build warehouse hierarchy cache if not already built
    if not _warehouse_cache:
        build_warehouse_hierarchy_cache()

    # Single query to get all bin data
    for item_code, warehouse, projected_qty in frappe.db.sql(
        """select item_code, warehouse, projected_qty
        from tabBin where item_code in ({})
            and (warehouse != '' and warehouse is not null)""".format(
            ", ".join(["%s"] * len(items_to_consider))
        ),
        items_to_consider,
    ):
        if item_code not in item_warehouse_projected_qty:
            item_warehouse_projected_qty.setdefault(item_code, {})

        if warehouse not in item_warehouse_projected_qty.get(item_code):
            item_warehouse_projected_qty[item_code][warehouse] = flt(projected_qty)

        # Use cached warehouse hierarchy instead of fetching each time
        parent_warehouses = get_parent_warehouses_cached(warehouse)
        for parent_warehouse in parent_warehouses:
            if not item_warehouse_projected_qty.get(item_code, {}).get(parent_warehouse):
                item_warehouse_projected_qty.setdefault(item_code, {})[
                    parent_warehouse
                ] = flt(projected_qty)
            else:
                item_warehouse_projected_qty[item_code][parent_warehouse] += flt(
                    projected_qty
                )

    return item_warehouse_projected_qty


def build_warehouse_hierarchy_cache():
    """
    Build warehouse hierarchy cache
    - Single query to get all warehouse parent relationships
    - Cached for the entire reorder run
    """
    global _warehouse_cache

    # Get all warehouse parent relationships in one query
    warehouse_data = frappe.db.sql(
        """
        SELECT name, parent_warehouse
        FROM `tabWarehouse`
        WHERE disabled = 0
        """,
        as_dict=True,
    )

    # Build cache
    for row in warehouse_data:
        _warehouse_cache[row.name] = {
            "parent": row.parent_warehouse,
            "hierarchy": [],
        }

    # Build hierarchy for each warehouse
    for warehouse in _warehouse_cache.keys():
        parents = []
        current = warehouse
        visited = set()  # Prevent infinite loops

        while _warehouse_cache.get(current, {}).get("parent"):
            parent = _warehouse_cache[current]["parent"]
            if parent in visited:
                break  # Circular reference protection
            visited.add(parent)
            parents.append(parent)
            current = parent

        _warehouse_cache[warehouse]["hierarchy"] = parents


def get_parent_warehouses_cached(warehouse):
    """Get parent warehouses from cache"""
    return _warehouse_cache.get(warehouse, {}).get("hierarchy", [])


def process_item_for_reorder(
    item_code,
    item_data,
    item_warehouse_projected_qty,
    warehouse_company,
    default_company,
    material_requests,
):
    """Process a single item for reorder and add to appropriate MR group"""

    if item_data.warehouse not in warehouse_company:
        # disabled warehouse
        return

    reorder_level = flt(item_data.warehouse_reorder_level)
    reorder_qty = flt(item_data.warehouse_reorder_qty)

    # Get projected qty
    if item_data.warehouse_group:
        projected_qty = flt(
            item_warehouse_projected_qty.get(item_code, {}).get(item_data.warehouse_group)
        )
    else:
        projected_qty = flt(
            item_warehouse_projected_qty.get(item_code, {}).get(item_data.warehouse)
        )

    # Check if reorder needed
    if (reorder_level or reorder_qty) and projected_qty <= reorder_level:
        deficiency = reorder_level - projected_qty
        if deficiency > reorder_qty:
            reorder_qty = deficiency

        company = warehouse_company.get(item_data.warehouse) or default_company

        # Group key: (company, warehouse, material_request_type)
        # This creates one MR per warehouse instead of multiple MRs
        group_key = (
            company,
            item_data.warehouse,
            item_data.material_request_type,
        )

        if group_key not in material_requests:
            material_requests[group_key] = []

        material_requests[group_key].append(
            {
                "item_code": item_code,
                "warehouse": item_data.warehouse,
                "reorder_qty": reorder_qty,
                "item_details": frappe._dict(
                    {
                        "item_code": item_code,
                        "name": item_code,
                        "item_name": item_data.item_name,
                        "item_group": item_data.item_group,
                        "brand": item_data.brand,
                        "description": item_data.description,
                        "stock_uom": item_data.stock_uom,
                        "purchase_uom": item_data.purchase_uom,
                        "lead_time_days": item_data.lead_time_days,
                    }
                ),
            }
        )


def create_cumulative_material_requests(material_requests):
    """
    Create cumulative material requests
    - One MR per (company, warehouse, type) combination
    - Multiple items in single MR
    """
    mr_list = []
    exceptions_list = []

    def _log_exception(mr):
        if frappe.local.message_log:
            exceptions_list.extend(frappe.local.message_log)
            frappe.local.message_log = []
        else:
            exceptions_list.append(frappe.get_traceback(with_context=True))

        mr.log_error("Unable to create material request")

    company_wise_mr = frappe._dict({})

    for group_key, items in material_requests.items():
        company, warehouse, request_type = group_key

        try:
            if not items:
                continue

            mr = frappe.new_doc("Material Request")
            mr.update(
                {
                    "company": company,
                    "transaction_date": nowdate(),
                    "material_request_type": "Material Transfer"
                    if request_type == "Transfer"
                    else request_type,
                }
            )

            schedule_dates = []

            for d in items:
                d = frappe._dict(d)
                item = d.get("item_details")
                uom = item.stock_uom
                conversion_factor = 1.0

                if request_type == "Purchase":
                    uom = item.purchase_uom or item.stock_uom
                    if uom != item.stock_uom:
                        conversion_factor = (
                            frappe.db.get_value(
                                "UOM Conversion Detail",
                                {"parent": item.name, "uom": uom},
                                "conversion_factor",
                            )
                            or 1.0
                        )

                must_be_whole_number = frappe.db.get_value(
                    "UOM", uom, "must_be_whole_number", cache=True
                )
                qty = d.reorder_qty / conversion_factor
                if must_be_whole_number:
                    from math import ceil
                    qty = ceil(qty)

                # Calculate schedule date
                schedule_date = add_days(nowdate(), cint(item.lead_time_days))
                schedule_dates.append(schedule_date)

                mr.append(
                    "items",
                    {
                        "doctype": "Material Request Item",
                        "item_code": d.item_code,
                        "schedule_date": schedule_date,
                        "qty": qty,
                        "conversion_factor": conversion_factor,
                        "uom": uom,
                        "stock_uom": item.stock_uom,
                        "warehouse": d.warehouse,
                        "item_name": item.item_name,
                        "description": item.description,
                        "item_group": item.item_group,
                        "brand": item.brand,
                    },
                )

            mr.schedule_date = max(schedule_dates or [nowdate()])
            mr.flags.ignore_mandatory = True

            # Set custom field if in auto reorder process
            frappe.flags.in_auto_reorder_process = True
            mr.insert()
            mr.submit()
            frappe.flags.in_auto_reorder_process = False

            mr_list.append(mr)

            company_wise_mr.setdefault(company, []).append(mr)

        except Exception:
            frappe.flags.in_auto_reorder_process = False
            _log_exception(mr)

    # Send email notifications
    if company_wise_mr:
        if getattr(frappe.local, "reorder_email_notify", None) is None:
            frappe.local.reorder_email_notify = cint(
                frappe.db.get_value("Stock Settings", None, "reorder_email_notify")
            )

        if frappe.local.reorder_email_notify:
            send_email_notification(company_wise_mr)

    if exceptions_list:
        notify_errors(exceptions_list)

    return mr_list


def send_email_notification(company_wise_mr):
    """Notify user about auto creation of Material Requests"""
    for company, mr_list in company_wise_mr.items():
        email_list = get_email_list(company)

        if not email_list:
            continue

        msg = frappe.render_template(
            "templates/emails/reorder_item.html", {"mr_list": mr_list}
        )

        frappe.sendmail(
            recipients=email_list,
            subject=_("Auto Material Requests Generated"),
            message=msg,
        )


def get_email_list(company):
    """Get email list for notifications"""
    users = get_company_wise_users(company)
    user_table = frappe.qb.DocType("User")
    role_table = frappe.qb.DocType("Has Role")

    query = (
        frappe.qb.from_(user_table)
        .inner_join(role_table)
        .on(user_table.name == role_table.parent)
        .select(user_table.email)
        .where(
            (role_table.role.isin(["Purchase Manager", "Stock Manager"]))
            & (user_table.name.notin(["Administrator", "All", "Guest"]))
            & (user_table.enabled == 1)
            & (user_table.docstatus < 2)
        )
    )

    if users:
        query = query.where(user_table.name.isin(users))

    emails = query.run(as_dict=True)

    return list(set([email.email for email in emails]))


def get_company_wise_users(company):
    """Get users with access to company"""
    companies = [company]

    if parent_company := frappe.db.get_value("Company", company, "parent_company"):
        companies.append(parent_company)

    users = frappe.get_all(
        "User Permission",
        filters={
            "allow": "Company",
            "for_value": ("in", companies),
            "apply_to_all_doctypes": 1,
        },
        fields=["user"],
    )

    return [user.user for user in users]


def notify_errors(exceptions_list):
    """Notify system managers about errors"""
    import json

    subject = _("[Important] [ERPNext] Auto Reorder Errors")
    content = (
        _("Dear System Manager,")
        + "<br>"
        + _(
            "An error occurred for certain Items while creating Material Requests based on Re-order level. Please rectify these issues :"
        )
        + "<br>"
    )

    for exception in exceptions_list:
        try:
            exception = json.loads(exception)
            error_message = """<div class='small text-muted'>{}</div><br>""".format(
                _(exception.get("message"))
            )
            content += error_message
        except Exception:
            pass

    content += _("Regards,") + "<br>" + _("Administrator")

    from frappe.email import sendmail_to_system_managers

    sendmail_to_system_managers(subject, content)
