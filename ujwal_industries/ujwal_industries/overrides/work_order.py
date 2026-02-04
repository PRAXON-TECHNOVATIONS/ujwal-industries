import frappe

@frappe.whitelist()
def set_wip_from_production_item(production_item): 
    """ 
    Auto-set Work Order WIP warehouse based on Production Item's Item Defaults (company-wise).
    - 1 Work Order = 1 WIP Warehouse 
    - Production Item decides the shop floor 
    Fetch WIP warehouse from Item Defaults for given production item & company.
    Called from Work Order JS. 
    """
    
    if not production_item:
        return None

    company = frappe.defaults.get_user_default("Company") \
              or frappe.db.get_single_value("Global Defaults", "default_company")

    if not company:
        return None

    return frappe.db.get_value(
        "Item Default",
        {
            "parent": production_item,
            "company": company,
        },
        "custom_wip_warehouse",
    )