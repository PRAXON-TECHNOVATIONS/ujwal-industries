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
		// Set query filter for employee field in custom_user_list child table
		// Only show employees with Manufacturing Manager or Manufacturing User role
		frm.set_query("employee", "custom_user_list", function() {
			return {
				query: "ujwal_industries.ujwal_industries.overrides.workstation.get_manufacturing_employees"
			};
		});
	},

	refresh: function(frm) {
		// Subscribe to real-time status updates
		setup_workstation_realtime(frm);

		// Show status indicator
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
			// Update the status field in the form
			frm.doc.status = data.status;
			frm.refresh_field("status");

			// Update status indicator
			update_status_indicator(frm);

			// Show notification
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
		case "Production":
			color = "green";
			break;
		case "Problem":
			color = "red";
			break;
		case "Maintenance":
			color = "orange";
			break;
		case "Off":
			color = "darkgrey";
			break;
		case "Idle":
			color = "yellow";
			break;
		case "Setup":
			color = "blue";
			break;
	}

	frm.page.set_indicator(status, color);
}
