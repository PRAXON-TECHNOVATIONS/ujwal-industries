# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Work Order Process Time Calculation

Calculates total process time from Work Order creation to completion:
- Start: Work Order creation datetime
- Material Transfer: First Material Transfer for Manufacture stock entry
- Job Card Execution: All job card completion times
- End: Last Manufacture stock entry submission
"""

import frappe
from frappe import _
from frappe.utils import (
	get_datetime,
	time_diff_in_hours,
	time_diff_in_seconds,
	format_duration,
	now_datetime
)


@frappe.whitelist()
def get_process_time(work_order):
	"""
	Calculate and return total process time for a Work Order.

	Args:
		work_order (str): Work Order name

	Returns:
		dict: Process time data with timeline
	"""
	if not work_order:
		return None

	wo = frappe.get_doc("Work Order", work_order)

	# Start time: Work Order creation
	start_time = get_datetime(wo.creation)

	# Get all Stock Entries linked to this Work Order
	stock_entries = frappe.db.sql("""
		SELECT
			name,
			stock_entry_type,
			purpose,
			posting_date,
			posting_time,
			docstatus
		FROM
			`tabStock Entry`
		WHERE
			work_order = %(work_order)s
			AND docstatus = 1
		ORDER BY
			posting_date, posting_time
	""", {"work_order": work_order}, as_dict=1)

	# Get all Job Cards linked to this Work Order
	job_cards = frappe.db.sql("""
		SELECT
			name,
			operation,
			status,
			actual_start_date,
			actual_end_date,
			total_time_in_mins
		FROM
			`tabJob Card`
		WHERE
			work_order = %(work_order)s
			AND docstatus = 1
		ORDER BY
			actual_start_date
	""", {"work_order": work_order}, as_dict=1)

	# Build timeline
	timeline = []

	# 1. Work Order Creation
	timeline.append({
		"stage": "Work Order Created",
		"start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
		"end_time": None,
		"duration": None
	})

	# 2. Material Transfer for Manufacture
	material_transfers = [se for se in stock_entries if se.purpose == "Material Transfer for Manufacture"]
	if material_transfers:
		first_transfer = material_transfers[0]
		transfer_time = get_datetime(f"{first_transfer.posting_date} {first_transfer.posting_time}")
		transfer_duration = time_diff_in_hours(transfer_time, start_time)

		timeline.append({
			"stage": f"Material Transfer ({first_transfer.name})",
			"start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
			"end_time": transfer_time.strftime("%Y-%m-%d %H:%M:%S"),
			"duration": format_duration(transfer_duration * 3600, hide_days=False)  # Convert hours to seconds
		})

	# 3. Job Card Execution
	if job_cards:
		total_job_time = 0
		for jc in job_cards:
			if jc.actual_start_date and jc.actual_end_date:
				jc_start = get_datetime(jc.actual_start_date)
				jc_end = get_datetime(jc.actual_end_date)
				jc_duration = time_diff_in_hours(jc_end, jc_start)
				total_job_time += jc_duration

				timeline.append({
					"stage": f"Job Card: {jc.operation} ({jc.name})",
					"start_time": jc_start.strftime("%Y-%m-%d %H:%M:%S"),
					"end_time": jc_end.strftime("%Y-%m-%d %H:%M:%S"),
					"duration": format_duration(jc_duration * 3600, hide_days=False)
				})

	# 4. Manufacture Stock Entries
	manufacture_entries = [se for se in stock_entries if se.purpose == "Manufacture"]
	if manufacture_entries:
		last_manufacture = manufacture_entries[-1]  # Get the last one
		end_time = get_datetime(f"{last_manufacture.posting_date} {last_manufacture.posting_time}")

		# Find the previous stage end time for duration calculation
		prev_time = start_time
		if job_cards and job_cards[-1].actual_end_date:
			prev_time = get_datetime(job_cards[-1].actual_end_date)
		elif material_transfers:
			prev_time = get_datetime(f"{material_transfers[0].posting_date} {material_transfers[0].posting_time}")

		manufacture_duration = time_diff_in_hours(end_time, prev_time)

		timeline.append({
			"stage": f"Manufacture Complete ({last_manufacture.name})",
			"start_time": prev_time.strftime("%Y-%m-%d %H:%M:%S"),
			"end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
			"duration": format_duration(manufacture_duration * 3600, hide_days=False)
		})

		# Calculate total time
		total_time_hours = time_diff_in_hours(end_time, start_time)
	else:
		# If no manufacture entry yet, calculate up to now
		end_time = now_datetime()
		total_time_hours = time_diff_in_hours(end_time, start_time)

	# Format total time
	total_time_formatted = format_duration(total_time_hours * 3600, hide_days=False)

	# Determine status color
	status_color = "blue"
	if wo.status == "Completed":
		status_color = "green"
	elif wo.status == "Stopped":
		status_color = "red"
	elif wo.status in ["In Process", "Not Started"]:
		status_color = "orange"

	return {
		"work_order": work_order,
		"start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
		"end_time": end_time.strftime("%Y-%m-%d %H:%M:%S") if manufacture_entries else None,
		"total_time_hours": total_time_hours,
		"total_time_formatted": total_time_formatted,
		"status_color": status_color,
		"timeline": timeline,
		"stock_entries_count": len(stock_entries),
		"job_cards_count": len(job_cards)
	}
