// Copyright (c) 2026, Ujwal Industries
// Custom overrides for Workstation
frappe.ui.form.on('Workstation', {
    onload: function(frm) {
        frm.set_query('custom_asset_name', function() {
            return {
                filters: {
                    asset_category: 'Workstation'
                }
            };
        });
    }
});

frappe.ui.form.on("Workstation", {
	setup: function(frm) {
		// Only show employees with Manufacturing Manager or Manufacturing User role
		frm.set_query("employee", "custom_user_list", function() {
			return {
				query: "ujwal_industries.ujwal_industries.overrides.workstation.get_manufacturing_employees"
			};
		});
	},

	refresh: function(frm) {
		setup_workstation_realtime(frm);
		update_status_indicator(frm);
	},

	onload: function(frm) {
		setup_workstation_realtime(frm);
	}
});

/**
 * Setup real-time subscription for this workstation's status changes
 */
function setup_workstation_realtime(frm) {
	if (frm._realtime_subscribed) {
		return;
	}

	frappe.realtime.on("workstation_status_changed", function(data) {
		if (data.workstation === frm.doc.name) {
			frm.doc.status = data.status;
			frm.refresh_field("status");
			update_status_indicator(frm);

			const indicator = data.status === "Problem" ? "red" : "green";
			frappe.show_alert({
				message: __("Status changed to {0}", [data.status]),
				indicator: indicator
			}, 5);
		}
	});

	frm._realtime_subscribed = true;
}

/**
 * Update the page indicator based on workstation status
 */
function update_status_indicator(frm) {
	const status = frm.doc.status;
	let color = "blue";

	switch(status) {
		case "Production":  color = "green";    break;
		case "Problem":     color = "red";      break;
		case "Maintenance": color = "orange";   break;
		case "Off":         color = "darkgrey"; break;
		case "Idle":        color = "yellow";   break;
		case "Setup":       color = "blue";     break;
	}

	frm.page.set_indicator(status, color);
}

// ─── Cost Estimation: day-cost roll-up ───────────────────────────────────────

frappe.ui.form.on("Workstation", {
	custom_machine_emi_per_day: calculate_workstation_day_cost,
	custom_wages_per_shift: calculate_workstation_day_cost,
	custom_electricity_per_shift: calculate_workstation_day_cost,
	custom_factory_expenses_per_day: calculate_workstation_day_cost,
	custom_finance_cost_per_day: calculate_workstation_day_cost,
	custom_admin_cost_per_day: calculate_workstation_day_cost,
	custom_selling_dist_cost_per_day: calculate_workstation_day_cost,
	custom_shift_hours: calculate_workstation_day_cost,
});

function calculate_workstation_day_cost(frm) {
	const total = flt(frm.doc.custom_machine_emi_per_day)
		+ flt(frm.doc.custom_wages_per_shift)
		+ flt(frm.doc.custom_electricity_per_shift)
		+ flt(frm.doc.custom_factory_expenses_per_day)
		+ flt(frm.doc.custom_finance_cost_per_day)
		+ flt(frm.doc.custom_admin_cost_per_day)
		+ flt(frm.doc.custom_selling_dist_cost_per_day);

	frm.set_value("custom_total_cost_per_day", total);

	const shift_hours = flt(frm.doc.custom_shift_hours);
	frm.set_value("custom_cost_per_min", shift_hours ? total / 60 / shift_hours : 0);
}

// ─── Operator management patch on WorkstationDashboard ──────────────────────

(function patch_workstation_dashboard() {
	if (typeof WorkstationDashboard === "undefined") {
		// WorkstationDashboard not loaded yet – retry once the form refreshes
		return;
	}

	// 1. Replace the data-fetch call with our endpoint that includes employee_name
	WorkstationDashboard.prototype.prepapre_dashboard = function() {
		let me = this;
		frappe.call({
			method: "ujwal_industries.ujwal_industries.overrides.workstation.get_job_cards_with_operator",
			args: { workstation: me.frm.doc.name },
			callback: function(r) {
				if (r.message) {
					me.job_cards = r.message;
					me.render_job_cards();
				}
			},
		});
	};

	// 2. After the standard template is rendered, inject operator UI
	const _orig_render = WorkstationDashboard.prototype.render_job_cards;
	WorkstationDashboard.prototype.render_job_cards = function() {
		_orig_render.call(this);
		this._inject_operator_ui();
		this._fix_card_layout();
	};

	// 3. After start/complete updates the card, re-inject operator UI
	const _orig_update = WorkstationDashboard.prototype.update_job_card_details;
	WorkstationDashboard.prototype.update_job_card_details = function() {
		_orig_update.call(this);
		this._inject_operator_ui();
		this._fix_card_layout();
	};

	// 4. Start the job properly via make_time_log (sets started_time, employee field, etc.)
	WorkstationDashboard.prototype.start_job = function(job_card) {
		let me = this;
		frappe.prompt(
			[
				{
					fieldtype: "Datetime",
					label: __("Start Time"),
					fieldname: "start_time",
					reqd: 1,
					default: frappe.datetime.now_datetime(),
				},
				{
					label: __("Operator"),
					fieldname: "employee",
					fieldtype: "Link",
					options: "Employee",
					reqd: 1,
				},
			],
			function(data) {
				frappe.call({
					method: "ujwal_industries.ujwal_industries.overrides.workstation.start_job_with_operator",
					args: {
						job_card: job_card,
						employee: data.employee,
						from_time: data.start_time,
					},
					freeze: true,
					freeze_message: __("Starting job..."),
					callback: function(r) {
						if (!r.message) return;
						// Re-fetch all job cards so status, timer, and operator UI refresh
						me.prepapre_dashboard();
						me.frm.reload_doc();
					},
				});
			},
			__("Enter Value"),
			__("Start Job")
		);
	};

	// 5. Inject "Change Operator" button + current operator name for running cards
	WorkstationDashboard.prototype._inject_operator_ui = function() {
		let me = this;

		// Remove stale operator elements before re-rendering
		this.$wrapper.find(".btn-change-operator, .current-operator-display").remove();

		(this.job_cards || []).forEach(function(data) {
			if (!["Work In Progress", "On Hold"].includes(data.status)) return;

			// Find the active time log (no to_time = job is currently running)
			// Fall back to the most recent log if the job is paused between partial completions
			let active_log = null;
			let last_log = null;
			(data.time_logs || []).forEach(function(log) {
				if (!log.to_time) active_log = log;
				last_log = log;
			});

			let $card = me.$wrapper.find("[data-name='" + data.name + "']");
			let $btn_col = $card.find(".btn-complete").closest(".form-column");

			// "Change Operator" button – sits right after the Complete button
			$btn_col.find(".btn-complete").after(
				'<button style="width:130px;margin-top:5px;" '
				+ 'class="btn btn-default btn-xs btn-change-operator" '
				+ 'data-job-card="' + data.name + '">'
				+ __("Change Operator")
				+ '</button>'
			);

			// Current operator label below the buttons
			let display_log = active_log || last_log;
			let emp_display = display_log
				? (display_log.employee_name || display_log.employee || __("Not assigned"))
				: __("Not assigned");

			$btn_col.append(
				'<div class="current-operator-display text-muted" '
				+ 'data-job-card="' + data.name + '" '
				+ 'style="font-size:11px;margin-top:6px;line-height:1.4;">'
				+ __("Operator") + ': '
				+ '<strong class="operator-name">' + emp_display + '</strong>'
				+ '</div>'
			);
		});

		// Bind click once (use delegated event to avoid duplicates)
		this.$wrapper.off("click.change_op").on("click.change_op", ".btn-change-operator", function(e) {
			let job_card = $(e.currentTarget).data("job-card");
			me._change_operator_dialog(job_card);
		});
	};

	// 5b. Fix card heading (add item name) and link spacing/tap targets for every card
	WorkstationDashboard.prototype._fix_card_layout = function() {
		let me = this;

		(this.job_cards || []).forEach(function(data) {
			let $card = me.$wrapper.find("[data-name='" + data.name + "']");
			if (!$card.length) return;

			// Append item name to the heading: "Blanking - 200146 — Item Name"
			let $heading = $card.find(".section-head-job-card");
			if (data.production_item_name && !$heading.find(".job-card-item-name").length) {
				// Insert the item name text right before the collapse-indicator span
				let $indicator = $heading.find(".collapse-indicator-job");
				$indicator.before(
					'<span class="job-card-item-name text-muted" style="font-size:12px;">'
					+ ' — ' + frappe.utils.escape_html(data.production_item_name)
					+ '</span>'
				);
			}

			// Add spacing between Job Card and Work Order links so they don't
			// overlap as tap targets on mobile.
			let $links_col = $card.find(".frappe-control[title='" + __("Job Card") + "']").closest(".form-column");
			$links_col.find(".frappe-control[title='" + __("Job Card") + "']").css("margin-bottom", "10px");
			$links_col.find(".frappe-control[title='" + __("Work Order") + "']").css("margin-top", "10px");
		});
	};

	// 6. Dialog to pick the new operator and persist it
	WorkstationDashboard.prototype._change_operator_dialog = function(job_card) {
		let me = this;
		frappe.prompt(
			[
				{
					label: __("New Operator"),
					fieldname: "employee",
					fieldtype: "Link",
					options: "Employee",
					reqd: 1,
					description: __("The selected employee will replace the current operator on this machine"),
				},
			],
			function(data) {
				frappe.call({
					method: "ujwal_industries.ujwal_industries.overrides.workstation.change_operator",
					args: { job_card: job_card, employee: data.employee },
					freeze: true,
					callback: function(r) {
						if (!r.message) return;

						let display = r.message.employee_name || r.message.employee;

						// Update the name shown in the card without a full reload
						me.$wrapper
							.find(".current-operator-display[data-job-card='" + job_card + "'] .operator-name")
							.text(display);

						frappe.show_alert({
							message: __("Operator changed to {0}", [display]),
							indicator: "green",
						}, 5);
					},
				});
			},
			__("Change Operator"),
			__("Change")
		);
	};
})();
