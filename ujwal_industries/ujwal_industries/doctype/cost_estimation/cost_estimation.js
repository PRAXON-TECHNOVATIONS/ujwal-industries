// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cost Estimation", {
	refresh: function (frm) {
		calculate_rm_totals(frm);
	},
	inventory_carrying_pct: calculate_other_costs,
	packing_forwarding_pct: calculate_other_costs,
	rejection_pct: calculate_other_costs,
	profit_mode: calculate_totals,
	profit_pct: calculate_totals,
	profit_amount: calculate_totals,
});

frappe.ui.form.on("Cost Estimation RM Item", {
	rm_used: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.rm_used) {
			return;
		}
		frappe.db.get_value("Item", row.rm_used, "last_purchase_rate").then(({ message }) => {
			if (message.last_purchase_rate) {
				row.rm_rate_per_kg = message.last_purchase_rate;
			}
			frm.refresh_field("rm_items");
			calculate_rm_row(frm, cdt, cdn);
		});
	},
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
	rate_per_pc: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.workstation) {
			// no machine — rate_per_pc is typed directly, just re-sum totals
			calculate_totals(frm);
		}
	},
	workstation: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.workstation) {
			frm.refresh_field("operation_items");
			calculate_totals(frm);
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

	calculate_other_costs(frm);
}

function calculate_operation_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (row.workstation) {
		row.rate_per_pc = Math.ceil((flt(row.shift_rate_per_min) / flt(row.time_per_pc_min)) * 100) / 100;
	}
	frm.refresh_field("operation_items");
	calculate_other_costs(frm);
}

function calculate_other_costs(frm) {
	const base_for_pct = flt(frm.doc.net_rm_cost_per_pc) + get_total_labour_cost(frm);

	let rm_value_for_inventory = 0;
	(frm.doc.rm_items || []).forEach((row) => {
		rm_value_for_inventory += flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg);
	});

	frm.doc.inventory_carrying_cost = (rm_value_for_inventory * flt(frm.doc.inventory_carrying_pct)) / 100;
	frm.doc.packing_forwarding_cost = (base_for_pct * flt(frm.doc.packing_forwarding_pct)) / 100;
	frm.doc.rejection_cost = (base_for_pct * flt(frm.doc.rejection_pct)) / 100;

	frm.refresh_field("inventory_carrying_cost");
	frm.refresh_field("packing_forwarding_cost");
	frm.refresh_field("rejection_cost");

	calculate_totals(frm);
}

function get_total_labour_cost(frm) {
	let total_labour_cost = 0;
	(frm.doc.operation_items || []).forEach((row) => {
		total_labour_cost += flt(row.rate_per_pc);
	});
	frm.doc.total_labour_cost_per_pc = total_labour_cost;
	frm.refresh_field("total_labour_cost_per_pc");
	return total_labour_cost;
}

function calculate_totals(frm) {
	const total_labour_cost = get_total_labour_cost(frm);
	const base_for_pct = flt(frm.doc.net_rm_cost_per_pc) + total_labour_cost;

	frm.doc.total_cost_per_pc =
		base_for_pct +
		flt(frm.doc.inventory_carrying_cost) +
		flt(frm.doc.packing_forwarding_cost) +
		flt(frm.doc.rejection_cost);
	frm.refresh_field("total_cost_per_pc");

	if (frm.doc.profit_mode === "Percentage") {
		frm.doc.profit_amount = (base_for_pct * flt(frm.doc.profit_pct)) / 100;
		frm.refresh_field("profit_amount");
	}

	frm.doc.total_component_cost = flt(frm.doc.total_cost_per_pc) + flt(frm.doc.profit_amount);
	frm.refresh_field("total_component_cost");
}
