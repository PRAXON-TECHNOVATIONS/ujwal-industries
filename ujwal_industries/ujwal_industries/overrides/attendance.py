import frappe
from frappe import _
from frappe.utils import flt, formatdate, get_datetime, time_diff_in_hours

STANDARD_WORKING_HOURS = 8.5
OVERTIME_ELIGIBLE_TYPE = "Worker"

def calculate_working_and_overtime_hours(doc, method=None):
    doc.custom_working_hour = 0
    doc.custom_overtime_hours = 0

    if doc.status not in ("Present", "Half Day", "Work From Home"):
        return

    if not (doc.in_time and doc.out_time):
        return

    try:
        in_time = get_datetime(doc.in_time)
        out_time = get_datetime(doc.out_time)

        if out_time <= in_time:
            frappe.throw(
                _("Out Time ({0}) must be after In Time ({1}) for Employee {2} on {3}").format(
                    out_time,
                    in_time,
                    frappe.bold(doc.employee),
                    formatdate(doc.attendance_date),
                ),
                title=_("Invalid In / Out Time"),
            )

        working_hours = time_diff_in_hours(out_time, in_time)
        doc.custom_working_hour = flt(working_hours, 2)

        employment_type = frappe.get_cached_value("Employee", doc.employee, "employment_type")
        if employment_type == OVERTIME_ELIGIBLE_TYPE:
            doc.custom_overtime_hours = flt(max(working_hours - STANDARD_WORKING_HOURS, 0), 2)

    except frappe.ValidationError:
        raise

    except Exception:
        error_log = frappe.log_error(
            title=f"Attendance Hours Calculation Failed - {doc.employee}",
            message=frappe.get_traceback(),
            reference_doctype="Attendance",
            reference_name=doc.name,
        )

        frappe.throw(
            _(
                "Could not calculate Working / Overtime Hours for Employee {0} on {1}.<br>"
                "Please check Error Log: {2}"
            ).format(
                frappe.bold(doc.employee),
                formatdate(doc.attendance_date),
                frappe.utils.get_link_to_form("Error Log", error_log.name),
            ),
            title=_("Attendance Calculation Error"),
        )