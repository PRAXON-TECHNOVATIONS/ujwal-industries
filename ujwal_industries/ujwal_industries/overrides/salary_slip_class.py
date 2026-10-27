import frappe
from frappe.utils import cint, flt, getdate

from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip


class CustomSalarySlip(SalarySlip):
	def get_working_days_details(self, lwp=None, for_preview=0):
		super().get_working_days_details(lwp=lwp, for_preview=for_preview)

		if for_preview or not self.excludes_weekly_off():
			return

		# HRMS already dropped every holiday when this is off
		if not cint(frappe.db.get_single_value("Payroll Settings", "include_holidays_in_total_working_days")):
			return

		# Only weekly offs are removed; festival holidays stay paid
		self.total_working_days = flt(self.total_working_days) - len(
			self.get_weekly_offs(self.start_date, self.end_date)
		)

		if flt(self.payment_days):
			# A weekly off the employee worked on is paid like a normal day
			unpaid_weekly_offs = sum(
				1 - self.get_worked_fraction(date)
				for date in self.get_weekly_offs(self.actual_start_date, self.actual_end_date)
			)
			self.payment_days = max(flt(self.payment_days) - unpaid_weekly_offs, 0)

	def excludes_weekly_off(self):
		employment_type = frappe.get_cached_value("Employee", self.employee, "employment_type")
		return employment_type and cint(
			frappe.get_cached_value(
				"Employment Type", employment_type, "custom_exclude_weekly_off_from_working_days"
			)
		)

	def get_weekly_offs(self, start_date, end_date):
		holiday_list = get_holiday_list_for_employee(self.employee, raise_exception=False)
		if not holiday_list:
			return []

		return frappe.get_all(
			"Holiday",
			filters={
				"parent": holiday_list,
				"weekly_off": 1,
				"holiday_date": ["between", [getdate(start_date), getdate(end_date)]],
			},
			pluck="holiday_date",
		)

	def get_worked_fraction(self, date):
		status = frappe.db.get_value(
			"Attendance",
			{"employee": self.employee, "attendance_date": date, "docstatus": 1},
			"status",
		)
		if status in ("Present", "Work From Home"):
			return 1
		if status == "Half Day":
			return 1 - (
				flt(frappe.db.get_single_value("Payroll Settings", "daily_wages_fraction_for_half_day")) or 0.5
			)
		return 0
