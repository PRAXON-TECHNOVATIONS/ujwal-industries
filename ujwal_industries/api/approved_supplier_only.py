from frappe import whitelist, validate_and_sanitize_search_inputs, get_list
import json

@whitelist()
@validate_and_sanitize_search_inputs
def supplier_query(doctype, txt, searchfield, start, page_len, filters):

    doctype = "Supplier"

    base_filters = {
        "workflow_state": "Approved"
    }

    or_filters = [
        [searchfield, "like", f"%{txt}%"],
        ["supplier_name", "like", f"%{txt}%"],
    ]

    if isinstance(filters, str):
        filters = json.loads(filters)

    if isinstance(filters, list):
        filters.append(["Supplier", "workflow_state", "=", "Approved"])
        final_filters = filters
    else:
        base_filters.update(filters or {})
        final_filters = base_filters

    return get_list(
        doctype,
        filters=final_filters,
        fields=["name", "supplier_name"],
        limit_start=start,
        limit_page_length=page_len,
        order_by="name asc",
        or_filters=or_filters,
        as_list=True,
    )