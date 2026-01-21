// Copyright (c) 2026, Ujwal Industries
// Custom overrides for Job Card

frappe.ui.form.on("Job Card", {
	refresh: function(frm) {
		// Display downtime alerts if any exist
		show_downtime_alerts(frm);
	},

	prepare_timer_buttons: function(frm) {
		// Call the original prepare_timer_buttons first
		// This is a workaround since we can't call super() in Frappe
		_original_prepare_timer_buttons(frm);

		// Now override the Pause Job button behavior
		if (frm.doc.started_time || frm.doc.current_time) {
			if (frm.doc.status != "On Hold") {
				// Remove the default Pause Job button
				frm.page.remove_inner_button(__("Pause Job"));

				// Add our custom Pause Job button with dialog
				frm.add_custom_button(__("Pause Job"), () => {
					show_pause_reason_dialog(frm);
				});
			}
		}
	}
});

/**
 * Show dialog to capture pause reason
 */
function show_pause_reason_dialog(frm) {
	const fields = [
		{
			fieldtype: "Link",
			label: __("Pause Reason"),
			options: "Job Card Pause Reason",
			fieldname: "pause_reason",
			reqd: 1
		}
	];

	frappe.prompt(
		fields,
		(values) => {
			// Pause the job and save the reason
			pause_job_with_reason(frm, values.pause_reason);
		},
		__("Select Pause Reason"),
		__("Pause Job")
	);
}

/**
 * Pause job and save the pause reason
 */
function pause_job_with_reason(frm, pause_reason) {
	const args = {
		job_card_id: frm.doc.name,
		complete_time: frappe.datetime.now_datetime(),
		status: "On Hold",
		pause_reason: pause_reason
	};

	// Call custom method to handle pause with reason
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.job_card.pause_job_with_reason",
		args: {
			args: args
		},
		freeze: true,
		callback: function(r) {
			if (!r.exc) {
				frm.reload_doc();
				frm.trigger("make_dashboard");
				frappe.show_alert({
					message: __("Job paused successfully"),
					indicator: "orange"
				}, 5);
			}
		}
	});
}

/**
 * Original prepare_timer_buttons function
 * This duplicates the standard ERPNext behavior
 */
function _original_prepare_timer_buttons(frm) {
	frm.trigger("make_dashboard");

	if (!frm.doc.started_time && !frm.doc.current_time) {
		frm.add_custom_button(__("Start Job"), () => {
			if ((frm.doc.employee && !frm.doc.employee.length) || !frm.doc.employee) {
				frappe.prompt(
					{
						fieldtype: "Table MultiSelect",
						label: __("Select Employees"),
						options: "Job Card Time Log",
						fieldname: "employees",
					},
					(d) => {
						frm.events.start_job(frm, "Work In Progress", d.employees);
					},
					__("Assign Job to Employee")
				);
			} else {
				frm.events.start_job(frm, "Work In Progress", frm.doc.employee);
			}
		}).addClass("btn-primary");
	} else if (frm.doc.status == "On Hold") {
		frm.add_custom_button(__("Resume Job"), () => {
			frm.events.start_job(frm, "Resume Job", frm.doc.employee);
		}).addClass("btn-primary");
	} else {
		// Complete Job button
		frm.add_custom_button(__("Complete Job"), () => {
			var sub_operations = frm.doc.sub_operations;

			let set_qty = true;
			if (sub_operations && sub_operations.length > 1) {
				set_qty = false;
				let last_op_row = sub_operations[sub_operations.length - 2];

				if (last_op_row.status == "Complete") {
					set_qty = true;
				}
			}

			if (set_qty) {
				frappe.prompt(
					{
						fieldtype: "Float",
						label: __("Completed Quantity"),
						fieldname: "qty",
						default: frm.doc.for_quantity - frm.doc.total_completed_qty,
					},
					(data) => {
						frm.events.complete_job(frm, "Complete", data.qty);
					},
					__("Enter Value")
				);
			} else {
				frm.events.complete_job(frm, "Complete", 0.0);
			}
		}).addClass("btn-primary");
	}
}

/**
 * Display downtime alerts in the dashboard
 */
function show_downtime_alerts(frm) {
	// Check if there are downtime entries in __onload
	if (!frm.doc.__onload || !frm.doc.__onload.downtime_entries) {
		return;
	}

	const downtime_entries = frm.doc.__onload.downtime_entries;

	if (!downtime_entries || downtime_entries.length === 0) {
		return;
	}

	// Check if alert already exists to prevent duplicates
	if (frm._downtime_alert_shown) {
		return;
	}

	// Build alert message
	let alert_html = '<div style="padding: 10px; background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; margin-bottom: 10px;">';
	alert_html += '<h5 style="margin: 0 0 10px 0; color: #856404;"><i class="fa fa-exclamation-triangle"></i> Workstation Downtime Alert</h5>';

	downtime_entries.forEach(entry => {
		alert_html += '<div style="margin-bottom: 8px; padding: 8px; background-color: white; border-left: 3px solid #ffc107;">';
		alert_html += '<strong>Period:</strong> ' + frappe.datetime.str_to_user(entry.from_time) + ' to ' + frappe.datetime.str_to_user(entry.to_time) + '<br>';
		alert_html += '<strong>Reason:</strong> ' + (entry.stop_reason || 'N/A') + '<br>';

		if (entry.remarks) {
			alert_html += '<strong>Remarks:</strong> ' + entry.remarks + '<br>';
		}

		if (entry.downtime) {
			alert_html += '<strong>Downtime:</strong> ' + entry.downtime + ' mins<br>';
		}

		alert_html += '</div>';
	});

	alert_html += '</div>';

	// Add the alert to the dashboard
	frm.dashboard.add_comment(alert_html, 'yellow', true);

	// Mark that we've shown the alert to prevent duplicates
	frm._downtime_alert_shown = true;
}
