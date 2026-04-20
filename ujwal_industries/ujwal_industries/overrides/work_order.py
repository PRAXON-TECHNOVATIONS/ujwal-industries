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
    
# Works only when we creating a work order through production plan
def set_wip_before_insert(doc, method):
    if doc.production_item and not doc.wip_warehouse:
        company = doc.company
        wip = frappe.db.get_value(
            "Item Default",
            {
                "parent": doc.production_item,
                "company": company
            },
            "custom_wip_warehouse"
        )
        doc.wip_warehouse = wip
    
    
    if doc.amended_from:
        if frappe.db.exists("Work Order", doc.amended_from):
            frappe.delete_doc("Work Order", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None    


@frappe.whitelist()
def set_target_warehouse_from_production_item(production_item):
    """
    Auto-set Work Order Target (FG) Warehouse
    based on Production Item's Item Default (company-wise)
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
        "default_warehouse",
    )
