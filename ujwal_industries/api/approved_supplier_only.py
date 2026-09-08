from frappe import whitelist, validate_and_sanitize_search_inputs, get_list
import json

# Link-field dropdowns default to a small page_len (10-20), which hides most
# matches for a broad search term. Raise it to a high-but-bounded cap instead
# of removing the limit outright, so a very generic term can't return an
# unbounded result set and stall the dropdown or the DB.
MAX_SEARCH_RESULTS = 500


@whitelist()
@validate_and_sanitize_search_inputs
def supplier_query(doctype, txt, searchfield, start, page_len, filters):

    doctype = "Supplier"
    page_len = MAX_SEARCH_RESULTS

    base_filters = {
        "workflow_state": "Approved"
    }

    or_filters = [
        ["name", "like", f"%{txt}%"],
        ["custom_supplier_names", "like", f"%{txt}%"],
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
        fields=["name", "custom_supplier_names", "supplier_group"],
        limit_start=start,
        limit_page_length=page_len,
        order_by="name asc",
        or_filters=or_filters,
        as_list=True,
    )