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
        # Fresh slip (e.g. from Payroll Entry): pull structure components first, otherwise
        # adding the OT row makes HRMS skip loading the salary structure in validate.
        if not (doc.get("earnings") or doc.get("deductions")):
            doc.get_emp_and_working_day_details()

        ot_rate = flt(frappe.get_cached_value("Employee", doc.employee, "custom_ot_rate"))
        ot_amount = flt(flt(doc.custom_total_ot_hours) * ot_rate, 2)
        ot_component = frappe.db.get_single_value("Ujwal Industries Setting", "ot_salary_component")

        ot_rows = [d for d in doc.get("earnings", []) if ot_component and d.salary_component == ot_component]

        if not ot_amount:
            for row in ot_rows:
                doc.remove(row)
            return
    except Exception:
        throw_with_error_log(doc, "OT amount")

    if not ot_component:
        frappe.throw(
            _("Employee {0} has {1} OT hours but no OT Salary Component is set. Please set it in {2}.").format(
                frappe.bold(doc.employee),
                doc.custom_total_ot_hours,
                frappe.utils.get_link_to_form("Ujwal Industries Setting", "Ujwal Industries Setting"),
            ),
            title=_("OT Salary Component Missing"),
        )

    try:
        for extra_row in ot_rows[1:]:
            doc.remove(extra_row)

        if ot_rows:
            row = ot_rows[0]
        else:
            row = doc.append("earnings", {
                "salary_component": ot_component,
                "abbr": frappe.get_cached_value("Salary Component", ot_component, "salary_component_abbr"),
            })

        row.amount = ot_amount
        row.default_amount = ot_amount

    except Exception:
        throw_with_error_log(doc, "OT amount")


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