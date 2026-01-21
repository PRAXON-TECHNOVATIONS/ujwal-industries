// Copyright (c) 2026, Ujwal Industries
// Custom overrides for Workstation

frappe.ui.form.on("Workstation", {
	setup: function(frm) {
		// Set query filter for employee field in custom_user_list child table
		// Only show employees with Manufacturing Manager or Manufacturing User role
		frm.set_query("employee", "custom_user_list", function() {
			return {
				query: "ujwal_industries.ujwal_industries.overrides.workstation.get_manufacturing_employees"
			};
		});
	}
});
