# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

from __future__ import annotations

from typing import Any

import frappe


@frappe.whitelist()
def get_default_subcontracting_suppliers(
    items: list[str] | str, company: str
) -> dict[str, dict[str, Any]]:
    """
    Get default subcontracting suppliers for given items.

    Called from client-side JavaScript to fetch default suppliers
    for subcontract items in real-time.

    Args:
        items: List of item codes or single item code
        company: Company name

    Returns:
        Dict mapping item_code to supplier info:
        {
            "item_code": {
                "supplier": "Supplier Name",
                "lead_time_days": 3
            }
        }
    """
    # Handle JSON string from client
    import json
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (json.JSONDecodeError, TypeError):
            items = [items]

    if not items:
        return {}

    # Batch fetch default suppliers
    suppliers_data = frappe.db.sql(
        """
        SELECT
            parent as item_code,
            supplier,
            lead_time_days
        FROM `tabItem Subcontracting Supplier`
        WHERE parent IN %(items)s
          AND company = %(company)s
          AND is_default = 1
    """,
        {"items": items, "company": company},
        as_dict=True,
    )

    # Build result map
    result: dict[str, dict[str, Any]] = {}
    for row in suppliers_data:
        result[row.item_code] = {
            "supplier": row.supplier,
            "lead_time_days": row.lead_time_days or 0,
        }

    return result
