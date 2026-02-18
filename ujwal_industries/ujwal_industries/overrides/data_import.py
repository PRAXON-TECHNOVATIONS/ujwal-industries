# Copyright (c) 2026, Ujwal Industries
# License: MIT
# Custom Data Import validation for Production Plan backdated dates

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, get_datetime, nowdate, now_datetime


# Date fields to check for backdating in Production Plan import
# Only child table fields - main document fields like posting_date are excluded
PRODUCTION_PLAN_DATE_FIELDS = {
    # Child table: Production Plan Item (po_items)
    "Production Plan Item": [
        ("planned_start_date", "Datetime", "Planned Start Date"),
    ],
    # Child table: Production Plan Sub Assembly Item (sub_assembly_items)
    "Production Plan Sub Assembly Item": [
        ("schedule_date", "Datetime", "Schedule Date"),
        ("custom_schedule_end_date", "Datetime", "Schedule End Date"),
    ],
    # Child table: Material Request Plan Item (mr_items)
    "Material Request Plan Item": [
        ("schedule_date", "Date", "Schedule Date"),
        ("custom_start_date", "Date", "Start Date"),
    ],
}

# Excel column header patterns for each field (for matching)
COLUMN_HEADER_PATTERNS = {
    "planned_start_date": ["Planned Start Date", "planned_start_date"],
    "schedule_date": ["Schedule Date", "schedule_date"],
    "custom_schedule_end_date": ["Schedule End Date", "custom_schedule_end_date"],
    "custom_start_date": ["Start Date", "custom_start_date"],
}


def validate_production_plan_import(doc: Document, method: str | None = None) -> None:
    """
    Validate Production Plan Data Import for backdated dates.

    This function is called via doc_events hook on Data Import validate.
    It checks if the import is for Production Plan and validates that:
    1. If allow_backdated_planned_start_date is unchecked in Manufacturing Settings
    2. And the Excel file contains any backdated dates
    3. Then throw a clear error message to the user

    Args:
        doc: Data Import document
        method: Hook method name (unused)
    """
    del method  # Unused but required for hook signature
    
    # Only process Production Plan imports
    if doc.reference_doctype != "Production Plan":
        return

    # Only validate when there's an import file
    if not doc.import_file:
        return

    # Check the Manufacturing Settings
    allow_backdated = frappe.db.get_single_value(
        "Manufacturing Settings", "allow_backdated_planned_start_date"
    )

    # If backdated dates are allowed, no validation needed
    if allow_backdated:
        return

    # Validate the import file for backdated dates
    backdated_issues = _check_excel_for_backdated_dates(doc.import_file)

    if backdated_issues:
        _raise_backdated_error(backdated_issues)


def _check_excel_for_backdated_dates(import_file: str) -> list[dict[str, Any]]:
    """
    Read the Excel file and check for backdated dates.

    Args:
        import_file: Path to the import file (e.g., /private/files/xyz.xlsx)

    Returns:
        List of backdated date issues with row, column, field, and value info
    """
    from openpyxl import load_workbook

    issues = []
    today = getdate()
    today_datetime = now_datetime()

    # Get the full file path
    file_path = frappe.get_site_path() + import_file

    try:
        wb = load_workbook(file_path, data_only=True)
        ws = wb.active
    except Exception as e:
        frappe.log_error(f"Error reading import file for backdated validation: {e}")
        return []

    # Get headers from first row
    headers = [cell.value for cell in ws[1]]

    # Find columns that contain date fields we care about
    date_columns = _find_date_columns(headers)

    if not date_columns:
        return []

    # Check each row for backdated values
    for row_num in range(2, ws.max_row + 1):
        row_data = [cell.value for cell in ws[row_num]]

        for col_idx, field_info in date_columns.items():
            if col_idx >= len(row_data):
                continue

            value = row_data[col_idx]
            if value is None:
                continue

            # Check if the date is backdated
            is_backdated, date_value = _is_date_backdated(value, field_info["fieldtype"], today, today_datetime)

            if is_backdated:
                issues.append({
                    "row": row_num,
                    "column": col_idx + 1,  # 1-indexed for user display
                    "header": field_info["header"],
                    "fieldname": field_info["fieldname"],
                    "label": field_info["label"],
                    "value": str(date_value),
                    "child_table": field_info.get("child_table", ""),
                })

    return issues


def _find_date_columns(headers: list[str | None]) -> dict[int, dict[str, Any]]:
    """
    Find columns in the Excel that correspond to date fields we need to validate.

    Args:
        headers: List of column headers from Excel

    Returns:
        Dictionary mapping column index to field info
    """
    date_columns = {}

    for col_idx, header in enumerate(headers):
        if header is None:
            continue

        header_str = str(header).strip()

        # Check each child table's date fields
        for doctype, fields in PRODUCTION_PLAN_DATE_FIELDS.items():
            for fieldname, fieldtype, label in fields:
                # Check if header matches this field
                if _header_matches_field(header_str, fieldname, label, doctype):
                    # Determine child table from doctype
                    child_table = ""
                    if doctype == "Production Plan Item":
                        child_table = "po_items"
                    elif doctype == "Production Plan Sub Assembly Item":
                        child_table = "sub_assembly_items"
                    elif doctype == "Material Request Plan Item":
                        child_table = "mr_items"

                    date_columns[col_idx] = {
                        "fieldname": fieldname,
                        "fieldtype": fieldtype,
                        "label": label,
                        "header": header_str,
                        "doctype": doctype,
                        "child_table": child_table,
                    }
                    break

    return date_columns


def _header_matches_field(header: str, fieldname: str, label: str, doctype: str) -> bool:
    """
    Check if an Excel header matches a field.

    Handles patterns like:
    - "Planned Start Date (Assembly Items)"
    - "Schedule Date (sub_assembly_items)"
    - "Start Date (Raw Materials)"
    """
    header_lower = header.lower()

    # Child table indicators for each doctype
    child_indicators = {
        "Production Plan Item": ["assembly items", "po_items", "assembly"],
        "Production Plan Sub Assembly Item": ["sub_assembly", "sub assembly", "sfg"],
        "Material Request Plan Item": ["raw materials", "mr_items", "material"],
    }

    indicators = child_indicators.get(doctype, [])

    # Direct match with fieldname
    if fieldname.lower() in header_lower:
        # If header has parentheses, check if any indicator matches
        if "(" in header:
            return any(ind in header_lower for ind in indicators)
        # If no parentheses, still check for indicator anywhere in header
        return any(ind in header_lower for ind in indicators)

    # Match with label
    if label.lower() in header_lower:
        if "(" in header:
            return any(ind in header_lower for ind in indicators)
        return any(ind in header_lower for ind in indicators)

    return False


def _is_date_backdated(
    value: Any,
    fieldtype: str,
    today: datetime,
    today_datetime: datetime
) -> tuple[bool, Any]:
    """
    Check if a date value is backdated (before today).

    Args:
        value: The date value from Excel (could be datetime, string, etc.)
        fieldtype: "Date" or "Datetime"
        today: Today's date
        today_datetime: Current datetime

    Returns:
        Tuple of (is_backdated, parsed_date_value)
    """
    try:
        if isinstance(value, datetime):
            date_value = value
        elif isinstance(value, str):
            # Try to parse the string
            try:
                date_value = get_datetime(value)
            except Exception:
                date_value = getdate(value)
        else:
            # Try to convert to date
            date_value = getdate(value)

        # Compare based on fieldtype
        if fieldtype == "Datetime":
            compare_date = getdate(date_value)
        else:
            compare_date = getdate(date_value)

        is_backdated = compare_date < today
        return is_backdated, date_value

    except Exception:
        # If we can't parse the date, don't flag it as an error
        return False, value


def _raise_backdated_error(issues: list[dict[str, Any]]) -> None:
    """
    Raise a user-friendly error message for backdated dates.

    Args:
        issues: List of backdated date issues
    """
    # Group issues by child table for better readability
    grouped = {}
    for issue in issues:
        table = issue.get("child_table") or "Main Document"
        if table not in grouped:
            grouped[table] = []
        grouped[table].append(issue)

    # Build error message
    error_lines = [
        _("Cannot import Production Plan with backdated dates."),
        "",
        _("The setting <b>'Allow Backdated Planned Start Date'</b> in Manufacturing Settings is <b>unchecked</b>."),
        "",
        _("The following backdated dates were found in your import file:"),
        "",
    ]

    table_labels = {
        "po_items": _("Assembly Items (FG)"),
        "sub_assembly_items": _("Sub Assembly Items (SFG)"),
        "mr_items": _("Raw Materials (MR)"),
    }

    for table, table_issues in grouped.items():
        table_label = table_labels.get(table, table)
        error_lines.append(f"<b>{table_label}:</b>")

        # Show first 5 issues per table to avoid overwhelming the user
        for issue in table_issues[:5]:
            error_lines.append(
                f"  - Row {issue['row']}: {issue['label']} = <b>{issue['value']}</b>"
            )

        if len(table_issues) > 5:
            error_lines.append(f"  - ... and {len(table_issues) - 5} more")

        error_lines.append("")

    error_lines.extend([
        _("To proceed, you have two options:"),
        "",
        _("1. <b>Update the dates</b> in your Excel file to today or a future date"),
        _("2. <b>Enable backdated dates</b> by checking 'Allow Backdated Planned Start Date' in:"),
        _("   Manufacturing Settings > Production Planning Settings"),
    ])

    frappe.throw(
        msg="<br>".join(error_lines),
        title=_("Backdated Dates Not Allowed"),
        as_list=False
    )
