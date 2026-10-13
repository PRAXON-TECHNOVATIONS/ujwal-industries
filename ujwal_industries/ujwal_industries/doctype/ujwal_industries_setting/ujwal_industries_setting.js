// Copyright (c) 2026, Ujjwal Aggrawal and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ujwal Industries Setting", {
	setup(frm) {
		frm.set_query("ot_salary_component", () => ({
			filters: { type: "Earning" },
		}));
	},
});
