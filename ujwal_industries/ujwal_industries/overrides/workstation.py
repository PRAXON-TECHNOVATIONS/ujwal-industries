# Copyright (c) 2026, Ujwal Industries
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document  # type: ignore[import-untyped]


@frappe.whitelist()
def get_manufacturing_employees(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict[str, Any]) -> list[tuple[str]]:
    """
    Get employees who have Manufacturing Manager or Manufacturing User role.

    This query is used in the Workstation Users child table to filter employees
    by their user roles.

    Args:
        doctype: Employee doctype
        txt: Search text
        searchfield: Field to search in (usually 'name')
        start: Pagination start
        page_len: Number of records per page
        filters: Additional filters

    Returns:
        List of tuples containing employee name
    """
    # Get users who have Manufacturing Manager or Manufacturing User roles
    users_with_role = frappe.db.sql(
        """
        SELECT DISTINCT parent
        FROM `tabHas Role`
        WHERE role IN ('Manufacturing Manager', 'Manufacturing User')
        AND parenttype = 'User'
    """,
        as_dict=False,
    )

    if not users_with_role:
        return []

    # Extract user IDs from the result
    user_ids = [row[0] for row in users_with_role]

    # Get employees linked to these users
    employees = frappe.db.sql(
        """
        SELECT name, employee_name
        FROM `tabEmployee`
        WHERE user_id IN %(user_ids)s
        AND status = 'Active'
        AND (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
        ORDER BY
            CASE WHEN name LIKE %(txt)s THEN 0 ELSE 1 END,
            name
        LIMIT %(start)s, %(page_len)s
    """,
        {"user_ids": user_ids, "txt": f"%{txt}%", "start": start, "page_len": page_len},
        as_dict=False,
    )

    return employees


def has_permission_query_workstation(user: str) -> str | None:
    """
    Permission query for Workstation doctype.

    If the user is not a Manufacturing Manager, System Manager,
    they can only see workstations where they are added in custom_user_list.

    Args:
        user: User ID

    Returns:
        SQL condition string or None
    """

    # Check if user has Manufacturing Manager or System Manager role
    roles = frappe.get_roles(user)

    if "Manufacturing Manager" in roles or "System Manager" in roles or "Planning supervisor" in roles:
        # Full access - can see all workstations
        return None

    # Get employee linked to this user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")

    if not employee:
        # No employee record - no access to workstations
        return "1=0"

    # Get workstations where this employee is in custom_user_list
    workstations = frappe.db.sql(
        """
        SELECT DISTINCT parent
        FROM `tabWorkstation Users`
        WHERE employee = %s
        AND parenttype = 'Workstation'
    """,
        (employee,),
        as_dict=False,
    )

    if not workstations:
        # Not assigned to any workstation
        return "1=0"

    workstation_names = [row[0] for row in workstations]

    # Return condition to filter workstations
    return f"`tabWorkstation`.`name` IN ({', '.join(repr(w) for w in workstation_names)})"


def has_permission_query_job_card(user: str) -> str | None:
    """
    Permission query for Job Card doctype.

    If the user is not a Manufacturing Manager, System Manager,
    they can only see job cards for workstations where they are assigned.

    Args:
        user: User ID

    Returns:
        SQL condition string or None
    """

    # Check if user has Manufacturing Manager or System Manager role
    roles = frappe.get_roles(user)

    if "Manufacturing Manager" in roles or "System Manager" in roles or "Planning supervisor" in roles:
        # Full access - can see all job cards
        return None

    # Get employee linked to this user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")

    if not employee:
        # No employee record - no access to job cards
        return "1=0"

    # Get workstations where this employee is in custom_user_list
    workstations = frappe.db.sql(
        """
        SELECT DISTINCT parent
        FROM `tabWorkstation Users`
        WHERE employee = %s
        AND parenttype = 'Workstation'
    """,
        (employee,),
        as_dict=False,
    )

    if not workstations:
        # Not assigned to any workstation
        return "1=0"

    workstation_names = [row[0] for row in workstations]

    # Return condition to filter job cards by workstation
    return f"`tabJob Card`.`workstation` IN ({', '.join(repr(w) for w in workstation_names)})"


def has_permission_workstation(doc: Document, user: str, permission_type: str) -> bool:
    """
    Row-level permission check for Workstation doctype.

    This function is called for each individual document to check if user has permission.
    Unlike permission_query_conditions.

    Args:
        doc: Workstation document
        user: User ID
        permission_type: Type of permission (read, write, etc.)

    Returns:
        True if user has permission, False otherwise
    """
    # Check if user has Manufacturing Manager or System Manager role
    roles = frappe.get_roles(user)

    if "Manufacturing Manager" in roles or "System Manager" in roles or "Planning supervisor" in roles:
        # Full access
        return True

    # Get employee linked to this user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")

    if not employee:
        # No employee record - no access
        return False

    # Check if employee is in the workstation's custom_user_list
    has_access = frappe.db.exists(
        "Workstation Users",
        {"parent": doc.name, "parenttype": "Workstation", "employee": employee}
    )

    return bool(has_access)


def has_permission_job_card(doc: Document, user: str, permission_type: str) -> bool:
    """
    Row-level permission check for Job Card doctype.

    This function is called for each individual document to check if user has permission.
    Unlike permission_query_conditions.

    Args:
        doc: Job Card document
        user: User ID
        permission_type: Type of permission (read, write, etc.)

    Returns:
        True if user has permission, False otherwise
    """
    # Check if user has Manufacturing Manager or System Manager role
    roles = frappe.get_roles(user)

    if "Manufacturing Manager" in roles or "System Manager" in roles or "Planning supervisor" in roles:
        # Full access
        return True

    # Get employee linked to this user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")

    if not employee:
        # No employee record - no access
        return False

    # Get the workstation for this job card
    workstation = doc.workstation

    if not workstation:
        # No workstation assigned - no access
        return False

    # Check if employee is in the workstation's custom_user_list
    has_access = frappe.db.exists(
        "Workstation Users",
        {"parent": workstation, "parenttype": "Workstation", "employee": employee}
    )

    return bool(has_access)
