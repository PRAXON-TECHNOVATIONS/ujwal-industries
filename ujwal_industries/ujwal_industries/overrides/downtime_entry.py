# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Downtime Entry overrides for workstation status management.

This module handles:
1. Updating workstation status to "Problem" when a downtime entry is active
2. Reverting workstation status when downtime ends
3. Real-time sync of workstation status changes
"""

from __future__ import annotations
import frappe
def validate_downtime_entry(doc, method=None):
    """
    Make to_time non-mandatory ONLY for job-card linked downtime.
    """
    if doc.custom_job_card:
        # job-card downtime → allow open entry
        return

    # workstation downtime → to_time REQUIRED
    if not doc.to_time:
        frappe.throw("To Time is mandatory for workstation downtime entries")


def on_save_downtime_entry(doc: Document, method: str | None = None) -> None:
    """
    Update workstation status when a downtime entry is saved.

    If the downtime is currently active (from_time <= now <= to_time),
    set the workstation status to "Problem".

    Args:
        doc: Downtime Entry document
        method: Event method name (unused)
    """
    _ = method

    if not doc.workstation:
        return

    update_workstation_status_for_downtime(doc.workstation)


def on_trash_downtime_entry(doc: Document, method: str | None = None) -> None:
    """
    Update workstation status when a downtime entry is deleted.

    Re-evaluates if there are any other active downtimes for the workstation.

    Args:
        doc: Downtime Entry document
        method: Event method name (unused)
    """
    _ = method

    if not doc.workstation:
        return

    # Re-check after this entry is deleted
    # Use flags to exclude current doc from the check
    frappe.flags.exclude_downtime_entry = doc.name
    update_workstation_status_for_downtime(doc.workstation)
    frappe.flags.exclude_downtime_entry = None


def update_workstation_status_for_downtime(workstation: str) -> None:
    """
    Check if there's an active downtime for the workstation and update status accordingly.

    Args:
        workstation: Workstation name
    """
    from frappe.utils import now_datetime

    current_time = now_datetime()

    # Build filters to find active downtimes
    filters = {
        "workstation": workstation,
        "from_time": ("<=", current_time),
        "to_time": (">=", current_time),
    }

    # Exclude the downtime being deleted if applicable
    exclude_entry = frappe.flags.get("exclude_downtime_entry")
    if exclude_entry:
        filters["name"] = ("!=", exclude_entry)

    # Check if there's any active downtime
    active_downtime = frappe.db.exists("Downtime Entry", filters)

    # Get current workstation status
    current_status = frappe.db.get_value("Workstation", workstation, "status")

    if active_downtime:
        # There's an active downtime - set status to Problem
        if current_status != "Problem":
            _set_workstation_status(workstation, "Problem", current_status)
    else:
        # No active downtime - revert status if currently Problem
        if current_status == "Problem":
            # Get the previous status from cache or default to Production
            previous_status = get_previous_workstation_status(workstation)
            _set_workstation_status(workstation, previous_status, current_status)


def _set_workstation_status(workstation: str, new_status: str, old_status: str) -> None:
    """
    Set workstation status and publish real-time update.

    Args:
        workstation: Workstation name
        new_status: New status to set
        old_status: Previous status (for caching)
    """
    # Store the previous status before changing to Problem
    if new_status == "Problem" and old_status != "Problem":
        cache_previous_workstation_status(workstation, old_status)

    # Update the workstation status
    frappe.db.set_value("Workstation", workstation, "status", new_status, update_modified=False)

    # Publish real-time update
    frappe.publish_realtime(
        event="workstation_status_changed",
        message={
            "workstation": workstation,
            "status": new_status,
            "old_status": old_status,
        },
        doctype="Workstation",
        docname=workstation,
        after_commit=True,
    )

    # Also publish to Job Cards using this workstation
    _publish_to_job_cards(workstation, new_status)


def _publish_to_job_cards(workstation: str, status: str) -> None:
    """
    Publish status update to all open Job Cards using this workstation.

    Args:
        workstation: Workstation name
        status: New workstation status
    """
    job_cards = frappe.get_all(
        "Job Card",
        filters={
            "workstation": workstation,
            "docstatus": 0,
            "status": ["not in", ["Completed", "Cancelled"]],
        },
        pluck="name",
    )

    for job_card in job_cards:
        frappe.publish_realtime(
            event="workstation_status_changed",
            message={
                "workstation": workstation,
                "status": status,
            },
            doctype="Job Card",
            docname=job_card,
            after_commit=True,
        )


def cache_previous_workstation_status(workstation: str, status: str) -> None:
    """
    Cache the workstation status before it's changed to Problem.

    Args:
        workstation: Workstation name
        status: Status to cache
    """
    cache_key = f"workstation_prev_status:{workstation}"
    frappe.cache.set_value(cache_key, status, expires_in_sec=86400 * 7)  # 7 days


def get_previous_workstation_status(workstation: str) -> str:
    """
    Get the cached previous status for a workstation.

    Args:
        workstation: Workstation name

    Returns:
        Previous status or "Production" as default
    """
    cache_key = f"workstation_prev_status:{workstation}"
    previous_status = frappe.cache.get_value(cache_key)
    return previous_status or "Production"


def sync_workstation_statuses() -> None:
    """
    Scheduled job to sync workstation statuses based on active downtimes.

    This runs every minute to:
    1. Find downtimes that have just started and set workstation to "Problem"
    2. Find downtimes that have just ended and revert workstation status

    Should be called from scheduler.
    """
    from frappe.utils import now_datetime

    current_time = now_datetime()

    # Get all workstations that have downtime entries (active, just started, or just ended)
    # We look at entries within a 2-minute window to catch transitions
    workstations_with_downtimes = frappe.db.sql(
        """
        SELECT DISTINCT workstation
        FROM `tabDowntime Entry`
        WHERE (
            (from_time <= %(now)s AND to_time >= %(now)s)
            OR (from_time BETWEEN DATE_SUB(%(now)s, INTERVAL 2 MINUTE) AND %(now)s)
            OR (to_time BETWEEN DATE_SUB(%(now)s, INTERVAL 2 MINUTE) AND %(now)s)
        )
        """,
        {"now": current_time},
        as_dict=True,
    )

    for row in workstations_with_downtimes:
        update_workstation_status_for_downtime(row.workstation)

    # Also check workstations that are in "Problem" status but might not have active downtimes
    problem_workstations = frappe.get_all(
        "Workstation",
        filters={"status": "Problem"},
        pluck="name",
    )

    for workstation in problem_workstations:
        update_workstation_status_for_downtime(workstation)
