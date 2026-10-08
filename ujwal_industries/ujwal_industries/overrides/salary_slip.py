import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import flt, formatdate

OT_COMPONENT = "OT Rate"


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
                & (Attendance.docstatus != 2)
                & (Attendance.attendance_date.between(doc.start_date, doc.end_date))
            )
        ).run()

        doc.custom_total_ot_hours = flt(total[0][0] if total else 0, 2)

    except Exception:
        throw_with_error_log(doc, "Total OT Hours")

    set_ot_earning(doc)


def set_ot_earning(doc):
    try:
        ot_rate = flt(frappe.get_cached_value("Employee", doc.employee, "custom_ot_rate"))
        ot_amount = flt(flt(doc.custom_total_ot_hours) * ot_rate, 2)

        ot_rows = [d for d in doc.get("earnings", []) if d.salary_component == OT_COMPONENT]

        if not ot_amount:
            for row in ot_rows:
                doc.remove(row)
            return

        for extra_row in ot_rows[1:]:
            doc.remove(extra_row)

        if ot_rows:
            row = ot_rows[0]
        else:
            row = doc.append("earnings", {
                "salary_component": OT_COMPONENT,
                "abbr": frappe.get_cached_value("Salary Component", OT_COMPONENT, "salary_component_abbr"),
            })

        row.amount = ot_amount
        row.default_amount = ot_amount

    except Exception:
        throw_with_error_log(doc, "OT Rate amount")


def throw_with_error_log(doc, what):
    error_log = frappe.log_error(
        title=f"Salary Slip {what} Calculation Failed - {doc.employee}",
        message=frappe.get_traceback(),
        reference_doctype="Salary Slip",
        reference_name=doc.name,
    )

    frappe.throw(
        _(
            "Could not calculate {0} for Employee {1} ({2} to {3}).<br>"
            "Please check Error Log: {4}"
        ).format(
            what,
            frappe.bold(doc.employee),
            formatdate(doc.start_date),
            formatdate(doc.end_date),
            frappe.utils.get_link_to_form("Error Log", error_log.name),
        ),
        title=_("Overtime Calculation Error"),
    )