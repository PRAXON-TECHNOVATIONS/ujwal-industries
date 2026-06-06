// Copyright (c) 2026, Ujwal Industries
// Custom overrides for Job Card

function update_balance_qty(frm) {
	frm.set_value("custom_balance_qty", flt(frm.doc.for_quantity) - flt(frm.doc.total_completed_qty));
}

frappe.ui.form.on("Job Card", {
	onload(frm) {
		if (!frm.is_new()) {
			render_tool_summary(frm);
			update_balance_qty(frm);
		}
	},

	refresh(frm) {
		if (!frm.is_new()) {
			render_tool_summary(frm);
			update_balance_qty(frm);
		}
	},

	for_quantity(frm) {
		update_balance_qty(frm);
	},

	total_completed_qty(frm) {
		update_balance_qty(frm);
	},

	setup: function (frm) {
		get_filtered_tools(frm);
	},

	operation: function (frm) {
		frm.set_value("tool", null);
	},

	bom_no: function (frm) {
		frm.set_value("tool", null);
	},

	custom_tool_name: function (frm) {
		//  1. Check if Tool Is on Maintanance Period
		//  2. Pop Option to Add Reson for changes Tool
		if (frm.doc.custom_tool_name) {

			frappe.call({
				method: "ujwal_industries.ujwal_industries.overrides.job_card.check_tool_maintenance",
				args: {
					tool: frm.doc.custom_tool_name
				},
				callback: function (r) {
					if (r.message) {
						//  1. Check if Tool Is on Maintanance Period 
						frappe.msgprint(r.message);
						frm.set_value("custom_tool_name", null);
					}
					else {
						//  2. Check If Privious Tool added then Pop Option to Add Reson for changes Tool
						if (frm.doc.custom_previous_tool) {
							frappe.run_serially([
								() => {

									frm.set_value("custom_reason_for_tool_change", '');
									let old_tool = frm.doc.custom_previous_tool;

									let d = new frappe.ui.Dialog({
										title: "Reason for Tool Change",
										fields: [
											{
												label: "Reason",
												fieldname: "reason",
												fieldtype: "Small Text",
												reqd: 1
											}
										],
										primary_action_label: "Submit",
										primary_action(values) {
											frm.set_value("custom_reason_for_tool_change", values.reason);

											frappe.call({
												method: "ujwal_industries.ujwal_industries.overrides.job_card.create_tool_maintenance",
												args: {
													tool: old_tool,
													reason: values.reason
												},
												callback: function (res) {
													if (res && res.message) {
														frappe.msgprint({
															title: "Success",
															message: "<b>Tool Maintenance Created Successfully</b>",
															indicator: "green"
														});
													}
												},
											});

											d.hide();
										}
									});
									d.show();
								},


								() => {
									frm.refresh()

								}
							])
						}
					}
				}
			});
		}
	},
});

function render_tool_summary(frm) {
	if (!frm.fields_dict.custom_tool_summary) return;

	const toolMap = {};

	(frm.doc.time_logs || []).forEach(row => {
		if (!row.custom_tool) return;

		const qty = flt(row.completed_qty || 0);
		toolMap[row.custom_tool] = [(toolMap[row.custom_tool] || 0) + qty, (row.custom_tool_reason || "")];
	});

	// No data
	if (!Object.keys(toolMap).length) {
		frm.fields_dict.custom_tool_summary.$wrapper.html(`
			<div class="text-muted" style="padding: 10px;">
				Tool summary not available yet.
			</div>
		`);
		return;
	}

	let html = `
		<div style="margin-bottom: 10px;">
			<h4>Tool-wise Production Summary</h4>
		</div>
		<table class="table table-bordered table-sm">
			<thead style="background-color: #f8f9fa;">
				<tr>
					<th style="width: 30%">Tool</th>
					<th style="width: 20%; text-align: right;">Produced Qty</th>
					<th style="width: 50%; text-align: right;">Reason for Tool Change</th>
				</tr>
			</thead>
			<tbody>
	`;
	Object.entries(toolMap).forEach(([tool, qty]) => {
		html += `
			<tr>
				<td>${tool}</td>
				<td style="text-align: right;">${qty[0]}</td>
				<td style="text-align: right;">${qty[1]}</td>
			</tr>
		`;
	});

	html += `
			</tbody>
		</table>
	`;
	frm.fields_dict.custom_tool_summary.$wrapper.html(html);
}

frappe.ui.form.on("Job Card", {
	refresh: function (frm) {
		// Set Qty To Manufacture as Read Only
		frm.set_df_property("for_quantity", "read_only", 1);
		// Display downtime alerts if any exist
		show_downtime_alerts(frm);
		// Subscribe to real-time workstation status updates
		setup_realtime_workstation_status(frm);
		hide_button(frm);
	},

	onload: function (frm) {
		// Also setup on load for initial subscription
		setup_realtime_workstation_status(frm);
	},

	prepare_timer_buttons: function (frm) {
		// Call the original prepare_timer_buttons first
		// This is a workaround since we can't call super() in Frappe
		_original_prepare_timer_buttons(frm);

		//  CHECK DOWNTIME
		const has_active_downtime = frm.doc.__onload && frm.doc.__onload.has_active_downtime;

		if (has_active_downtime) {
			// Remove Start Job Button
			frm.page.remove_inner_button(__("Start Job"));
			// Remove Resume Job Button
			frm.page.remove_inner_button(__("Resume Job"));
			// Remove Stopwatch
			hide_job_card_timer(frm);
		}

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
	},
});

function hide_button(frm) {
	const requires_tool = frm.doc.__onload && frm.doc.__onload.operation_requires_tool;
	if (requires_tool && !frm.doc.custom_tool_name) {
		frm.page.remove_inner_button(__("Start Job"));
		frm.page.remove_inner_button(__("Resume Job"));
		hide_job_card_timer(frm);
	}
}

function hide_job_card_timer(frm) {
	// Hide stopwatch shown in page header
	$(frm.page.wrapper)
		.find(".page-actions .custom-actions .stopwatch")
		.closest(".custom-actions")
		.hide();
}

function hide_job_card_timer(frm) {
	// Hide stopwatch shown in page header
	$(frm.page.wrapper)
		.find(".page-actions .custom-actions .stopwatch")
		.closest(".custom-actions")
		.hide();
}

/**
 * Show dialog to capture pause reason and counter readings
 */
function show_pause_reason_dialog(frm) {
	let tool_cavities = 1;

	// Default start counter = end counter of last time log (machine counter continuity),
	// falling back to 0 if no previous log exists.
	const time_logs = frm.doc.time_logs || [];
	const last_log = time_logs.length ? time_logs[time_logs.length - 1] : null;
	const default_start_counter = flt(last_log && last_log.custom_end_counter || 0);

	const d = new frappe.ui.Dialog({
		title: __("Pause Job"),
		fields: [
			{
				fieldtype: "Link",
				label: __("Pause Reason"),
				options: "Job Card Pause Reason",
				fieldname: "pause_reason",
				reqd: 1
			},
			{
				fieldtype: "Section Break",
				label: __("Machine Counter")
			},
			{
				fieldtype: "Float",
				label: __("Start Counter"),
				fieldname: "start_counter",
				reqd: 1,
				default: default_start_counter,
				description: __("Counter reading at job start")
			},
			{
				fieldtype: "Column Break"
			},
			{
				fieldtype: "Float",
				label: __("End Counter"),
				fieldname: "end_counter",
				reqd: 1,
				description: __("Current counter reading")
			},
			{
				fieldtype: "Section Break"
			},
			{
				fieldtype: "Int",
				label: __("No of Cavities"),
				fieldname: "no_of_cavities",
				read_only: 1,
				description: __("Fetched from tool")
			},
			{
				fieldtype: "Column Break"
			},
			{
				fieldtype: "Float",
				label: __("Counter Qty"),
				fieldname: "counter_qty",
				read_only: 1,
				description: __("End Counter − Start Counter")
			},
			{
				fieldtype: "Column Break"
			},
			{
				fieldtype: "Float",
				label: __("Completed Qty"),
				fieldname: "completed_qty",
				read_only: 1,
				description: __("Counter Qty × No of Cavities")
			}
		],
		primary_action_label: __("Pause Job"),
		primary_action(values) {
			const counter_qty = flt(values.end_counter) - flt(values.start_counter);
			if (counter_qty < 0) {
				frappe.msgprint(__("End Counter cannot be less than Start Counter"));
				return;
			}
			const completed_qty = counter_qty * tool_cavities;
			d.hide();
			pause_job_with_reason(frm, values.pause_reason, completed_qty, values.start_counter, values.end_counter);
		}
	});

	// Auto-calculate counter qty and completed qty
	function recalculate() {
		const start = flt(d.get_value("start_counter") || 0);
		const end = flt(d.get_value("end_counter") || 0);
		const counter_qty = Math.max(0, end - start);
		d.set_value("counter_qty", counter_qty);
		d.set_value("completed_qty", counter_qty * tool_cavities);
	}

	d.fields_dict.start_counter.$input.on("change", recalculate);
	d.fields_dict.end_counter.$input.on("change", recalculate);

	d.show();

	// Fetch cavity count from the current tool and set it
	if (frm.doc.custom_tool_name) {
		frappe.db.get_value("Asset", frm.doc.custom_tool_name, "custom_no_of_cavities", (r) => {
			tool_cavities = Math.max(1, flt(r.custom_no_of_cavities) || 1);
			d.set_value("no_of_cavities", tool_cavities);
			recalculate();
		});
	} else {
		d.set_value("no_of_cavities", 1);
	}
}

/**
 * Pause job and save the pause reason with completed qty and counter readings
 */
function pause_job_with_reason(frm, pause_reason, completed_qty, start_counter, end_counter) {
	const args = {
		job_card_id: frm.doc.name,
		complete_time: frappe.datetime.now_datetime(),
		status: "On Hold",
		pause_reason: pause_reason,
		completed_qty: flt(completed_qty || 0),
		start_counter: flt(start_counter || 0),
		end_counter: flt(end_counter || 0)
	};

	// Call custom method to handle pause with reason
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.job_card.pause_job_with_reason",
		args: {
			args: args
		},
		freeze: true,
		callback: function (r) {
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
 * Only shows currently active downtimes (where current time is within the downtime period)
 */
function show_downtime_alerts(frm) {
	// Check if there are downtime entries in __onload
	if (!frm.doc.__onload || !frm.doc.__onload.downtime_entries) {
		return;
	}

	const downtime_entries = frm.doc.__onload.downtime_entries;
	const has_active_downtime = frm.doc.__onload.has_active_downtime;

	if (!downtime_entries || downtime_entries.length === 0) {
		return;
	}

	// Check if alert already exists to prevent duplicates
	if (frm._downtime_alert_shown) {
		return;
	}

	// Filter to only active downtimes
	const active_downtimes = downtime_entries.filter(entry => entry.is_active);
	const upcoming_downtimes = downtime_entries.filter(entry => entry.is_upcoming);

	// Only show alert if there are active downtimes
	if (active_downtimes.length === 0) {
		// Optionally show a subtle indicator for upcoming downtimes
		if (upcoming_downtimes.length > 0) {
			show_upcoming_downtime_indicator(frm, upcoming_downtimes);
		}
		return;
	}

	// Build alert message for ACTIVE downtimes
	let alert_html = '<div style="padding: 10px; background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; margin-bottom: 10px;">';
	alert_html += '<h5 style="margin: 0 0 10px 0; color: #721c24;"><i class="fa fa-exclamation-circle"></i> Workstation Currently Down</h5>';

	active_downtimes.forEach(entry => {
		alert_html += '<div style="margin-bottom: 8px; padding: 8px; background-color: white; border-left: 3px solid #dc3545;">';
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
	frm.dashboard.add_comment(alert_html, 'red', true);

	// Mark that we've shown the alert to prevent duplicates
	frm._downtime_alert_shown = true;
}

/**
 * Show a subtle indicator for upcoming scheduled downtimes
 */
function show_upcoming_downtime_indicator(frm, upcoming_downtimes) {
	if (frm._upcoming_downtime_shown) {
		return;
	}

	let alert_html = '<div style="padding: 8px; background-color: #cce5ff; border: 1px solid #b8daff; border-radius: 4px; margin-bottom: 10px;">';
	alert_html += '<h6 style="margin: 0 0 8px 0; color: #004085;"><i class="fa fa-info-circle"></i> Scheduled Downtime</h6>';

	upcoming_downtimes.forEach(entry => {
		alert_html += '<div style="margin-bottom: 4px; font-size: 12px;">';
		alert_html += frappe.datetime.str_to_user(entry.from_time) + ' - ' + (entry.stop_reason || 'Scheduled maintenance');
		alert_html += '</div>';
	});

	alert_html += '</div>';

	frm.dashboard.add_comment(alert_html, 'blue', true);
	frm._upcoming_downtime_shown = true;
}

/**
 * Setup real-time subscription for workstation status changes
 */
function setup_realtime_workstation_status(frm) {
	// Avoid duplicate subscriptions
	if (frm._realtime_workstation_subscribed) {
		return;
	}

	frappe.realtime.on("workstation_status_changed", function (data) {
		// Check if this update is for our workstation
		if (data.workstation === frm.doc.workstation) {
			handle_workstation_status_change(frm, data);
		}
	});

	frm._realtime_workstation_subscribed = true;
}

/**
 * Handle workstation status change event
 */
function handle_workstation_status_change(frm, data) {
	const status = data.status;
	const workstation = data.workstation;

	// Clear existing alerts
	frm._downtime_alert_shown = false;
	frm._upcoming_downtime_shown = false;

	if (status === "Problem") {
		// Show immediate alert for workstation down
		show_workstation_problem_alert(frm, workstation);

		// Show desktop notification
		if (frappe.browser.has_permission && Notification.permission === "granted") {
			new Notification("Workstation Down", {
				body: `Workstation ${workstation} is now in Problem status`,
				icon: "/assets/frappe/images/frappe-icon.svg"
			});
		}
	} else {
		// Workstation is back up - reload to refresh the dashboard
		frappe.show_alert({
			message: __("Workstation {0} is now {1}", [workstation, status]),
			indicator: "green"
		}, 5);

		// Reload the form to get fresh downtime data
		frm.reload_doc();
	}
}

/**
 * Show alert when workstation goes into Problem status
 */
function show_workstation_problem_alert(frm, workstation) {
	// Remove any existing downtime alerts first
	$(frm.dashboard.wrapper).find('.dashboard-comment').remove();

	let alert_html = '<div style="padding: 10px; background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; margin-bottom: 10px;">';
	alert_html += '<h5 style="margin: 0 0 10px 0; color: #721c24;"><i class="fa fa-exclamation-circle"></i> Workstation Currently Down</h5>';
	alert_html += '<div style="margin-bottom: 8px; padding: 8px; background-color: white; border-left: 3px solid #dc3545;">';
	alert_html += '<strong>Workstation:</strong> ' + workstation + '<br>';
	alert_html += '<strong>Status:</strong> Problem<br>';
	alert_html += '<em>A downtime entry has been recorded for this workstation.</em>';
	alert_html += '</div>';
	alert_html += '</div>';

	frm.dashboard.add_comment(alert_html, 'red', true);

	// Also show a prominent alert
	frappe.show_alert({
		message: __("Workstation {0} is now DOWN", [workstation]),
		indicator: "red"
	}, 10);
}

// Recalculate completed_qty in a time log row from its counter readings × tool cavities
function recalc_time_log_qty(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const counter_qty = Math.max(0, flt(row.custom_end_counter) - flt(row.custom_start_counter));
	const tool = row.custom_tool;

	if (tool) {
		frappe.db.get_value("Asset", tool, "custom_no_of_cavities", (r) => {
			const cavities = Math.max(1, flt(r.custom_no_of_cavities) || 1);
			frappe.model.set_value(cdt, cdn, "completed_qty", counter_qty * cavities);
		});
	} else {
		frappe.model.set_value(cdt, cdn, "completed_qty", counter_qty);
	}
}

frappe.ui.form.on("Job Card Time Log", {
	custom_start_counter(frm, cdt, cdn) {
		recalc_time_log_qty(frm, cdt, cdn);
	},
	custom_end_counter(frm, cdt, cdn) {
		recalc_time_log_qty(frm, cdt, cdn);
	},
	custom_tool(frm, cdt, cdn) {
		recalc_time_log_qty(frm, cdt, cdn);
	}
});

function get_filtered_tools(frm) {
	frm.set_query("custom_tool_name", function (doc) {
		if (!doc.bom_no) {
			return {};
		}

		return {
			query: "ujwal_industries.ujwal_industries.overrides.job_card.get_filtered_tools",
			filters: {
				bom: doc.bom_no,
				operation: doc.operation || " "
			}
		};
	});
}