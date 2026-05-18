import frappe
from frappe import whitelist, validate_and_sanitize_search_inputs


@whitelist()
@validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Search Item by item_code (name) or item_name — both shown in dropdown."""
	txt = (txt or "").strip()
	if isinstance(filters, str):
		import json
		filters = json.loads(filters)

	extra_where = ""
	extra_values = []
	if isinstance(filters, dict):
		for field, value in filters.items():
			extra_where += f" AND `tab{doctype}`.`{field}` = %s"
			extra_values.append(value)

	sql = f"""
		SELECT
			`tabItem`.`name`,
			`tabItem`.`item_name`
		FROM `tabItem`
		WHERE `tabItem`.`disabled` = 0
		  AND (`tabItem`.`name` LIKE %s OR `tabItem`.`item_name` LIKE %s)
		  {extra_where}
		ORDER BY
			CASE WHEN `tabItem`.`name` LIKE %s THEN 0 ELSE 1 END,
			`tabItem`.`name`
		LIMIT %s OFFSET %s
	"""
	like = f"%{txt}%"
	return frappe.db.sql(sql, [like, like] + extra_values + [like, page_len, start])


@whitelist()
@validate_and_sanitize_search_inputs
def customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Search Customer by name (ID) or customer_name — both shown in dropdown."""
	txt = (txt or "").strip()
	if isinstance(filters, str):
		import json
		filters = json.loads(filters)

	extra_where = ""
	extra_values = []
	if isinstance(filters, dict):
		for field, value in filters.items():
			extra_where += f" AND `tabCustomer`.`{field}` = %s"
			extra_values.append(value)

	sql = f"""
		SELECT
			`tabCustomer`.`name`,
			`tabCustomer`.`customer_name`
		FROM `tabCustomer`
		WHERE `tabCustomer`.`disabled` = 0
		  AND (`tabCustomer`.`name` LIKE %s OR `tabCustomer`.`customer_name` LIKE %s)
		  {extra_where}
		ORDER BY
			CASE WHEN `tabCustomer`.`name` LIKE %s THEN 0 ELSE 1 END,
			`tabCustomer`.`name`
		LIMIT %s OFFSET %s
	"""
	like = f"%{txt}%"
	return frappe.db.sql(sql, [like, like] + extra_values + [like, page_len, start])
