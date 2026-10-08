import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import flt, formatdate


def set_total_ot_hours(doc, method=None):
    doc.custom_total_ot_hours = 0

    if not (doc.employee and doc.start_date and doc.end_date):
        return

    try:
        Attendance = frappe.qb.DocType("Attendance")

        total = (
            frappe.qb.from_(Attendance)
            .select(Coalesce(Sum(Attendance.custom_overtime_hours), 0))
            .where(
                (Attendance.employee == doc.employee)
                # & (Attendance.docstatus == 1)
                & (Attendance.attendance_date.between(doc.start_date, doc.end_date))
            )
        ).run()

        doc.custom_total_ot_hours = flt(total[0][0] if total else 0, 2)

    except Exception:
        error_log = frappe.log_error(
            title=f"Salary Slip OT Calculation Failed - {doc.employee}",
            message=frappe.get_traceback(),
            reference_doctype="Salary Slip",
            reference_name=doc.name,
        )

        frappe.throw(
            _(
                "Could not calculate Total OT Hours for Employee {0} ({1} to {2}).<br>"
                "Please check Error Log: {3}"
            ).format(
                frappe.bold(doc.employee),
                formatdate(doc.start_date),
                formatdate(doc.end_date),
                frappe.utils.get_link_to_form("Error Log", error_log.name),
            ),
            title=_("Overtime Calculation Error"),
        )