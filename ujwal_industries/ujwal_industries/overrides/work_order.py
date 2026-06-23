import frappe

STORE_INCHARGE_VISIBLE_STATUSES = ("In Process", "Not Started")


def get_planned_end_date_from_production_plan(doc):
	"""Return the planned end date from the Production Plan row that created this Work Order.

	Work Orders link to their source via either:
	  - production_plan_sub_assembly_item -> Production Plan Sub Assembly Item.custom_schedule_end_date
	  - production_plan_item              -> Production Plan Item.custom_planned_end_date
	"""
	if doc.get("production_plan_sub_assembly_item"):
		end = frappe.db.get_value(
			"Production Plan Sub Assembly Item",
			doc.production_plan_sub_assembly_item,
			"custom_schedule_end_date",
		)
		if end:
			return end

	if doc.get("production_plan_item"):
		end = frappe.db.get_value(
			"Production Plan Item",
			doc.production_plan_item,
			"custom_planned_end_date",
		)
		if end:
			return end

	return None


def set_planned_end_date_from_production_plan(doc, method=None):
	"""before_insert: stamp the Production Plan's end date onto the Work Order.

	The WO's own planned_end_date is otherwise only computed on submit; this carries
	the planned end date through from the Production Plan at creation time.
	"""
	if doc.get("planned_end_date"):
		return
	end = get_planned_end_date_from_production_plan(doc)
	if end:
		doc.planned_end_date = end


def preserve_production_plan_end_date(doc, method=None):
	"""on_submit: re-apply the Production Plan end date.

	ERPNext recomputes planned_end_date from the last operation's planned_end_time during
	create_job_card() on submit. We restore the Production Plan's date so it is preserved.
	"""
	end = get_planned_end_date_from_production_plan(doc)
	if end and doc.planned_end_date != end:
		doc.db_set("planned_end_date", end, update_modified=False)


def _is_store_incharge_limited(user: str) -> bool:
    if user == "Administrator":
        return False

    roles = frappe.get_roles(user)
    if "System Manager" in roles:
        return False

    return "Store Incharge" in roles


def has_permission_query_work_order(user: str) -> str | None:
    if not _is_store_incharge_limited(user):
        return None

    statuses = ", ".join(frappe.db.escape(status) for status in STORE_INCHARGE_VISIBLE_STATUSES)
    return f"`tabWork Order`.`status` IN ({statuses})"


def has_permission_work_order(doc, ptype: str, user: str, debug: bool = False) -> bool | None:
    if not _is_store_incharge_limited(user):
        return None

    if ptype == "create":
        return None

    return doc.get("status") in STORE_INCHARGE_VISIBLE_STATUSES


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
