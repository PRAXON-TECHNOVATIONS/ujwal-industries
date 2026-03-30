import re

import frappe


def autoname(doc, method=None):
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return

    item_prefix = _get_item_prefix(doc.item_code)
    category_prefix = _get_word_prefix(doc.asset_category)
    tool_type_letter = _get_tool_type_letter(doc.tool_type)

    if not item_prefix:
        frappe.throw("Item Code is required to generate Asset ID.")

    if not category_prefix:
        frappe.throw("Asset Category is required to generate Asset ID.")

    if not tool_type_letter:
        frappe.throw("Tool Type is required to generate Asset ID.")

    series_prefix = f"{item_prefix}-{category_prefix}-{tool_type_letter}-"
    next_number = _get_next_sequence(series_prefix)
    doc.name = f"{series_prefix}{next_number:02d}"


def _get_item_prefix(item_code):
    value = (item_code or "").strip().upper()
    if not value:
        return ""

    match = re.match(r"[A-Z]+", value)
    if match:
        return match.group(0)[:2]

    return _get_word_prefix(value)


def _get_word_prefix(value):
    cleaned_words = re.findall(r"[A-Za-z0-9]+", value or "")
    if not cleaned_words:
        return ""

    if len(cleaned_words) == 1:
        return cleaned_words[0][:2].upper()

    return "".join(word[0].upper() for word in cleaned_words[:2])


def _get_tool_type_letter(tool_type):
    value = (tool_type or "").strip().upper()
    return value[:1]


def _get_next_sequence(series_prefix):
    frappe.db.sql(
        """
        SELECT name
        FROM `tabAsset`
        WHERE name LIKE %s
        ORDER BY creation DESC
        LIMIT 1
        FOR UPDATE
        """,
        (f"{series_prefix}%",),
    )

    latest_name = frappe.db.sql(
        """
        SELECT name
        FROM `tabAsset`
        WHERE name LIKE %s
        ORDER BY CAST(SUBSTRING_INDEX(name, '-', -1) AS UNSIGNED) DESC
        LIMIT 1
        """,
        (f"{series_prefix}%",),
        as_list=True,
    )

    if not latest_name:
        return 1

    return cint(latest_name[0][0].rsplit("-", 1)[-1]) + 1


def cint(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
