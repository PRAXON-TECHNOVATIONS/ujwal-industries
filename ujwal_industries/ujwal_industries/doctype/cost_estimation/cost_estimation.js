// Copyright (c) 2026, Ujjwal Aggrawal and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cost Estimation", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Recalculate from BOM"), () => {
				frappe.confirm(
					__(
						"This will discard any manual edits to Raw Material, Machine, Labour, Scrap and Overhead rows, and rebuild everything fresh from the BOM and current masters. Continue?"
					),
					() => {
						frm.call("recalculate").then(() => frm.reload_doc());
					}
				);
			});
		}
	},
});

function recompute_row_amount(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	row.amount = flt(row.qty) * flt(row.rate);
	refresh_field(row.parentfield, frm.doc.name, cdt);
}

frappe.ui.form.on("Cost Estimation RM Item", {
	qty: (frm, cdt, cdn) => recompute_row_amount(frm, cdt, cdn),
	rate: (frm, cdt, cdn) => recompute_row_amount(frm, cdt, cdn),
});

frappe.ui.form.on("Cost Estimation Scrap Item", {
	qty: (frm, cdt, cdn) => recompute_row_amount(frm, cdt, cdn),
	rate: (frm, cdt, cdn) => recompute_row_amount(frm, cdt, cdn),
});

frappe.ui.form.on("Cost Estimation Machine Item", {
	time_in_mins: (frm, cdt, cdn) => {
		const row = locals[cdt][cdn];
		row.machine_cost = (flt(row.time_in_mins) / 60) * flt(row.hour_rate);
		refresh_field("machine_items");
	},
	hour_rate: (frm, cdt, cdn) => {
		const row = locals[cdt][cdn];
		row.machine_cost = (flt(row.time_in_mins) / 60) * flt(row.hour_rate);
		refresh_field("machine_items");
	},
});

frappe.ui.form.on("Cost Estimation Labour Item", {
	labour_hours: (frm, cdt, cdn) => recompute_labour_cost(cdt, cdn),
	head_count: (frm, cdt, cdn) => recompute_labour_cost(cdt, cdn),
	hourly_rate: (frm, cdt, cdn) => recompute_labour_cost(cdt, cdn),
});

function recompute_labour_cost(cdt, cdn) {
	const row = locals[cdt][cdn];
	row.labour_cost = flt(row.labour_hours) * flt(row.head_count || 1) * flt(row.hourly_rate);
	refresh_field("labour_items");
}
