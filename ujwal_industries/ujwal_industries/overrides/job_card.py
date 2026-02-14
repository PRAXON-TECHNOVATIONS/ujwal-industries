# Copyright (c) 2026, Ujwal Industries
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import flt

from erpnext.manufacturing.doctype.job_card.job_card import (
    make_time_log as _original_make_time_log,
)

# HELPER – FG AVAILABILITY
def get_fg_availability_internal(work_order: str, exclude_job_card: str | None = None):
    if not work_order:
        return 0, 0, 0

    wo = frappe.get_doc("Work Order", work_order)

    transferred_fg = flt(wo.material_transferred_for_manufacturing or 0)

    manufactured_fg = (
        frappe.db.sql(
            """
            SELECT SUM(total_completed_qty)
            FROM `tabJob Card`
            WHERE work_order=%s
              AND docstatus=1
              {exclude}
            """.format(
                exclude="AND name != %s" if exclude_job_card else ""
            ),
            tuple(
                [work_order, exclude_job_card]
                if exclude_job_card
                else [work_order]
            ),
        )[0][0]
        or 0
    )

    available_fg = transferred_fg - flt(manufactured_fg)
    if available_fg < 0:
        available_fg = 0

    return transferred_fg, manufactured_fg, available_fg

# START / RESUME JOB -VALIDATION

@frappe.whitelist()
def make_time_log_with_material_check(args):
    if isinstance(args, str):
        import json
        args = json.loads(args)

    job_card_id = args.get("job_card_id")
    status = args.get("status")

    if status in ("Work In Progress", "Resume Job"):
        jc = frappe.get_doc("Job Card", job_card_id)

        if jc.work_order:
            # Transferred FG from Work Order
            wo = frappe.get_doc("Work Order", jc.work_order)
            transferred_fg = flt(wo.material_transferred_for_manufacturing or 0)

            # Produced qty from ALL Job Cards
            produced_submitted = (
                frappe.db.sql(
                    """
                    SELECT SUM(total_completed_qty)
                    FROM `tabJob Card`
                    WHERE work_order=%s
                      AND docstatus=1
                    """,
                    jc.work_order,
                )[0][0]
                or 0
            )

            # Produced qty from CURRENT Job Card (DRAFT)
            produced_current = flt(jc.total_completed_qty or 0)

            total_produced = flt(produced_submitted) + flt(produced_current)

            available_fg = transferred_fg - total_produced
            if available_fg < 0:
                available_fg = 0

            if available_fg <= 0:
                frappe.throw(
                    title="No Quantity Available",
                    msg=f"""
                    <b>No production quantity available to continue this Job</b><br><br>

                    <b>Work Order:</b> {jc.work_order}<br>
                    <b>Material Transferred (FG):</b> {transferred_fg}<br>
                    <b>Already Produced:</b> {total_produced}<br>
                    <b>Available Qty:</b>
                    <span style="color:red;"><b>0</b></span><br><br>

                    Please transfer additional material against the Work Order
                    to resume or start this Job Card.
                    """
                )

    return _original_make_time_log(args)

# JOB CARD SAVE - VALIDATION

def validate_job_card_qty_fg_based(doc: Document, method=None):
    """
    Final authority validation.
    Runs on SAVE + SUBMIT.
    """

    if not doc.work_order:
        return

    transferred_fg, manufactured_fg, available_fg = get_fg_availability_internal(
        doc.work_order, exclude_job_card=doc.name
    )

    entered_qty = flt(doc.total_completed_qty)

    if entered_qty > available_fg:
        frappe.throw(
            title="Quantity Exceeds Material Transfer",
            msg=f"""
            <b>Production quantity exceeds transferred material</b><br><br>

            <b>Work Order:</b> {doc.work_order}<br>
            <b>Material Transferred for Manufacturing (FG):</b>
            <b>{transferred_fg}</b><br>

            <b>Already Manufactured:</b> {manufactured_fg}<br>
            <b>Available for this Job Card:</b>
            <span style="color:green;"><b>{available_fg}</b></span><br><br>

            <b>Entered Completed Qty:</b>
            <span style="color:red;"><b>{entered_qty}</b></span><br><br>

            Please transfer additional material against the Work Order
            to increase allowed production quantity.
            """
        )

def job_card_validate(doc: Document, method=None):
    validate_job_card_qty_fg_based(doc, method)

def _has_active_workstation_downtime(workstation: str) -> bool:
    if not workstation:
        return False
    
    from frappe.utils import now_datetime
    
    current_time = now_datetime()

    return bool(
        frappe.db.exists(
            "Downtime Entry",
            {
                "workstation": workstation,
                "from_time": ("<=", current_time),
                "to_time": (">=", current_time),
            },
        )
    )

def restrict_job_card_edit_during_downtime(doc: Document, method=None):
    if not doc.workstation:
        return
    if doc.docstatus != 0:
        return  # Allow submitted docs to remain untouched

    if _has_active_workstation_downtime(doc.workstation):
        frappe.throw(
            title="Workstation Under Downtime",
            msg=f"""
            Job Card cannot be modified while workstation <b>{doc.workstation}</b>
            is under active downtime.
            """
        )

def _get_item_tolerance(production_item: str) -> float:
    """Get tolerance percentage from Item master's custom_tolerance_ field."""
    if not production_item:
        return 0.0
    return flt(frappe.db.get_value("Item", production_item, "custom_tolerance_") or 0)


def _is_within_tolerance(
    current_qty: float, previous_qty: float, tolerance_percentage: float, precision: int
) -> bool:
    """
    Check if current_qty is within tolerance of previous_qty.

    For sequence validation, we allow current operation's completed_qty to exceed
    previous operation's completed_qty by up to the tolerance percentage.
    """
    if tolerance_percentage <= 0:
        return current_qty <= previous_qty

    tolerance_amount = flt((previous_qty * tolerance_percentage) / 100, precision)
    max_acceptable = flt(previous_qty + tolerance_amount, precision)

    return current_qty <= max_acceptable


def validate_sequence_id_with_tolerance(self) -> None:
    """
    Override of standard validate_sequence_id that applies tolerance-based validation.

    The standard ERPNext validation requires that completed quantity of current operation
    cannot exceed completed quantity of previous operations. This override allows a small
    tolerance (defined in Item master's custom_tolerance_ field) to account for minor
    measurement variations in manufacturing.

    For example, if previous operation has 1,600,000 completed and tolerance is 0.5%:
    - Tolerance amount = 1,600,000 * 0.5 / 100 = 8,000
    - Max acceptable for current operation = 1,608,000
    """
    from frappe import _
    from frappe.utils import get_link_to_form
    from frappe import bold

    if self.is_corrective_job_card:
        return

    if not (self.work_order and self.sequence_id):
        return

    precision = self.precision("total_completed_qty")

    current_operation_qty = 0.0
    data = self.get_current_operation_data()
    if data and len(data) > 0:
        current_operation_qty = flt(data[0].completed_qty)

    current_operation_qty += flt(self.total_completed_qty)

    # Get tolerance from Item master
    tolerance_percentage = _get_item_tolerance(self.production_item)

    data = frappe.get_all(
        "Work Order Operation",
        fields=["operation", "status", "completed_qty", "sequence_id"],
        filters={"docstatus": 1, "parent": self.work_order, "sequence_id": ("<", self.sequence_id)},
        order_by="sequence_id, idx",
    )

    message = "Job Card {}: As per the sequence of the operations in the work order {}".format(
        bold(self.name), bold(get_link_to_form("Work Order", self.work_order))
    )

    for row in data:
        previous_qty = flt(row.completed_qty, precision)
        current_qty = flt(current_operation_qty, precision)

        # Check if current qty exceeds previous qty beyond tolerance
        if not _is_within_tolerance(current_qty, previous_qty, tolerance_percentage, precision):
            if row.status != "Completed":
                frappe.throw(
                    _("{0}, complete the operation {1} before the operation {2}.").format(
                        message, bold(row.operation), bold(self.operation)
                    ),
                )
            else:
                # Calculate acceptable range for error message
                tolerance_amount = flt((previous_qty * tolerance_percentage) / 100, precision)
                max_acceptable = flt(previous_qty + tolerance_amount, precision)

                frappe.throw(
                    _(
                        "The completed quantity {0} of operation {1} exceeds the acceptable range.<br>"
                        "Previous operation {2} completed: {3}<br>"
                        "Tolerance: +{4}%<br>"
                        "Maximum acceptable: {5}"
                    ).format(
                        bold(current_qty),
                        bold(self.operation),
                        bold(row.operation),
                        bold(previous_qty),
                        bold(tolerance_percentage),
                        bold(max_acceptable),
                    )
                )


def _apply_job_card_patches() -> None:
    """Apply monkey-patches to JobCard class for tolerance-based validations."""
    from erpnext.manufacturing.doctype.job_card.job_card import JobCard

    # Override validate_sequence_id with tolerance-based version
    JobCard.validate_sequence_id = validate_sequence_id_with_tolerance


# Apply patches when module is loaded
_apply_job_card_patches()


@frappe.whitelist()
def pause_job_with_reason(args: dict[str, Any] | str) -> None:
    """
    Pause a job card and store the pause reason in the time log.

    This is a custom override of the standard pause functionality that also captures
    and stores the reason for pausing the job in the time log's custom_pause_reason field.

    Args:
        args: Dictionary containing:
            - job_card_id: Job Card name
            - complete_time: Time when job was paused
            - status: Should be "On Hold"
            - pause_reason: The pause reason from Job Card Pause Reason master
    """
    import json

    if isinstance(args, str):
        args = json.loads(args)

    job_card_id = args.get("job_card_id")
    pause_reason = args.get("pause_reason")

    if not job_card_id:
        frappe.throw("Job Card ID is required")

    # Get the job card document
    job_card = frappe.get_doc("Job Card", job_card_id)

    # Update sub-operation if needed (from standard ERPNext logic)
    if job_card.sub_operations and len(job_card.sub_operations) > 0:
        sub_operations = [d for d in job_card.sub_operations if d.status != "Complete"]
        if sub_operations and len(sub_operations) > 0:
            args["sub_operation"] = sub_operations[0].sub_operation

    # Call the standard make_time_log method to handle the actual pause
    from erpnext.manufacturing.doctype.job_card.job_card import make_time_log

    make_time_log(args)

    # Reload the job card to get the newly created time log
    job_card.reload()

    # Find the most recent time log entry (the one just created)
    if job_card.time_logs and len(job_card.time_logs) > 0:
        # The latest time log will be the last one
        latest_time_log = job_card.time_logs[-1]

        # Set the pause reason in the time log
        latest_time_log.custom_pause_reason = pause_reason

    # Save the job card to persist the pause reason in time log
    job_card.save(ignore_permissions=True)

    frappe.db.commit()


def onload_job_card(doc: Document, method: str | None = None) -> None:
    """
    Load downtime information for the Job Card's workstation into __onload.

    When a Job Card is loaded, this function checks if there are any downtime entries
    for the workstation. It identifies which downtimes are currently active (current time
    falls within the downtime period) and marks them accordingly.

    Args:
        doc: Job Card document
        method: Event method name (unused)
    """
    _ = method  # Unused but required for hook signature

    if not doc.workstation:
        return

    from frappe.utils import now_datetime, add_days, get_datetime

    # Get current system time
    current_time = now_datetime()

    # Look for downtime entries from 7 days ago to 7 days in the future
    # This ensures we catch recent past downtimes and upcoming scheduled downtimes
    start_range = add_days(current_time, -7)
    end_range = add_days(current_time, 7)

    # Find downtime entries for this workstation within the time range
    downtime_entries = frappe.db.sql(
        """
        SELECT
            name,
            from_time,
            to_time,
            stop_reason,
            remarks,
            downtime
        FROM `tabDowntime Entry`
        WHERE workstation = %(workstation)s
        AND from_time <= %(end_range)s
        AND to_time >= %(start_range)s
        ORDER BY from_time ASC
    """,
        {"workstation": doc.workstation, "start_range": start_range, "end_range": end_range},
        as_dict=True,
    )

    if downtime_entries:
        # Check each entry and mark if it's currently active
        has_active_downtime = False
        for entry in downtime_entries:
            from_time = get_datetime(entry.from_time)
            to_time = get_datetime(entry.to_time)

            # Check if current time is within the downtime period
            if from_time <= current_time <= to_time:
                entry["is_active"] = True
                has_active_downtime = True
            elif current_time < from_time:
                entry["is_active"] = False
                entry["is_upcoming"] = True
            else:
                entry["is_active"] = False
                entry["is_upcoming"] = False

        # Store downtime information in __onload for client-side access
        doc.set_onload("downtime_entries", downtime_entries)
        doc.set_onload("has_active_downtime", has_active_downtime)
        doc.set_onload("current_server_time", str(current_time))


def override_job_card_qty_validation(doc: Document, method: str | None = None) -> None:
    """
    Override the standard Job Card quantity validation on submit with tolerance-based validation.

    By default, ERPNext requires that (Total Completed Qty + Process Loss Qty) must equal
    Qty to Manufacture exactly. This override uses the Item's custom_tolerance_ field to allow
    completion within an acceptable range.

    Tolerance is defined as a percentage in the Item master's custom_tolerance_ field.
    For example, if custom_tolerance_ = 0.5 (representing 0.5%), then:
    - Qty to Manufacture = 100
    - Acceptable range = 100 ± 0.5 = 99.5 to 100.5

    If total_completed_qty falls within this range, we auto-adjust process_loss_qty
    to make the validation pass.

    This function should be hooked to Job Card's before_submit event.

    Args:
        doc: Job Card document
        method: Event method name (unused)
    """
    _ = method  # Unused but required for hook signature

    if not doc.for_quantity or not doc.production_item:
        return

    from frappe.utils import flt

    precision = doc.precision("total_completed_qty")
    total_completed_qty = flt(doc.total_completed_qty, precision)
    for_quantity = flt(doc.for_quantity, precision)

    # Get tolerance percentage from Item master's custom_tolerance_ field
    tolerance_percentage = flt(
        frappe.db.get_value("Item", doc.production_item, "custom_tolerance_") or 0
    )

    # Calculate tolerance amount
    # If tolerance is 0.5%, then tolerance_amount = for_quantity * 0.5 / 100
    tolerance_amount = flt((for_quantity * tolerance_percentage) / 100, precision)

    # Calculate acceptable range
    min_acceptable = flt(for_quantity - tolerance_amount, precision)
    max_acceptable = flt(for_quantity + tolerance_amount, precision)

    # Check if total_completed_qty is within tolerance
    if min_acceptable <= total_completed_qty <= max_acceptable:
        # Within tolerance - adjust process_loss_qty to make validation pass
        doc.process_loss_qty = for_quantity - total_completed_qty
    else:
        # Outside tolerance - let the standard validation throw an error
        # But enhance the error message to show the acceptable range
        frappe.throw(
            frappe._(
                "Total Completed Qty ({0}) is outside the acceptable tolerance range.<br>"
                "Qty to Manufacture: {1}<br>"
                "Tolerance: ±{2}%<br>"
                "Acceptable Range: {3} to {4}"
            ).format(
                frappe.bold(total_completed_qty),
                frappe.bold(for_quantity),
                frappe.bold(tolerance_percentage),
                frappe.bold(min_acceptable),
                frappe.bold(max_acceptable)
            )
        )
