// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cost Estimation", {
	refresh: function (frm) {
		calculate_rm_totals(frm);
	},
});

frappe.ui.form.on("Cost Estimation RM Item", {
	rm_used: calculate_rm_row,
	rm_rate_per_kg: calculate_rm_row,
	gross_wt_per_pc: calculate_rm_row,
	rm_items_remove: function (frm) {
		calculate_rm_totals(frm);
	},
});

frappe.ui.form.on("Cost Estimation Scrap Item", {
	scrap_description: calculate_scrap_row,
	scrap_rate_per_kg: calculate_scrap_row,
	scrap_wt_per_pc: calculate_scrap_row,
	scrap_items_remove: function (frm) {
		calculate_rm_totals(frm);
	},
});

frappe.ui.form.on("Cost Estimation Operation Item", {
	time_per_pc_min: calculate_operation_row,
	shift_rate_per_min: calculate_operation_row,
	workstation: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.workstation) {
			return;
		}
		frappe.db.get_value(
			"Workstation",
			row.workstation,
			["custom_cost_per_min", "custom_asset_name"]
		).then(({ message }) => {
			row.shift_rate_per_min = message.custom_cost_per_min;
			if (message.custom_asset_name) {
				frappe.db.get_value("Asset", message.custom_asset_name, "asset_name").then(({ message: asset }) => {
					row.machine_name = asset.asset_name;
					frm.refresh_field("operation_items");
				});
			}
			calculate_operation_row(frm, cdt, cdn);
		});
	},
	operation_items_remove: function (frm) {
		calculate_totals(frm);
	},
});

function calculate_rm_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	row.gross_rm_cost_per_pc = flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg);
	frm.refresh_field("rm_items");
	calculate_rm_totals(frm);
}

function calculate_scrap_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	row.scrap_price_per_pc = flt(row.scrap_wt_per_pc) * flt(row.scrap_rate_per_kg);
	frm.refresh_field("scrap_items");
	calculate_rm_totals(frm);
}

function calculate_rm_totals(frm) {
	let total_gross_rm_cost = 0;
	(frm.doc.rm_items || []).forEach((row) => {
		total_gross_rm_cost += flt(row.gross_rm_cost_per_pc);
	});

	let total_scrap_price = 0;
	(frm.doc.scrap_items || []).forEach((row) => {
		total_scrap_price += flt(row.scrap_price_per_pc);
	});

	frm.doc.total_gross_rm_cost_per_pc = total_gross_rm_cost;
	frm.doc.total_scrap_price_per_pc = total_scrap_price;
	frm.doc.net_rm_cost_per_pc = total_gross_rm_cost - total_scrap_price;

	frm.refresh_field("total_gross_rm_cost_per_pc");
	frm.refresh_field("total_scrap_price_per_pc");
	frm.refresh_field("net_rm_cost_per_pc");

	calculate_totals(frm);
}

function calculate_operation_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	row.rate_per_pc = Math.ceil(flt(row.time_per_pc_min) * flt(row.shift_rate_per_min) * 100) / 100;
	frm.refresh_field("operation_items");
	calculate_totals(frm);
}

function calculate_totals(frm) {
	let total_labour_cost = 0;
	(frm.doc.operation_items || []).forEach((row) => {
		total_labour_cost += flt(row.rate_per_pc);
	});

	frm.doc.total_labour_cost_per_pc = total_labour_cost;
	frm.doc.total_cost_per_pc = flt(frm.doc.net_rm_cost_per_pc) + total_labour_cost;

	frm.refresh_field("total_labour_cost_per_pc");
	frm.refresh_field("total_cost_per_pc");
}
