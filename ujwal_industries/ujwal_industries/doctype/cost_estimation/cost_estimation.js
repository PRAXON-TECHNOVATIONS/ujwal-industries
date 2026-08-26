// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cost Estimation", {
	setup: function (frm) {
		frm.set_query("bom", function () {
			return {
				filters: {
					item: frm.doc.item,
					docstatus: 1,
					is_active: 1,
				},
			};
		});
	},
	refresh: function (frm) {
		calculate_rm_totals(frm);
	},
	item: function (frm) {
		if (!frm.doc.item) {
			frm.set_value("bom", "");
			return;
		}
		// Link fields can fire their change event more than once for a
		// single pick in some interaction paths — guard against firing two
		// overlapping fetches for the same item.
		const item_at_trigger = frm.doc.item;
		if (frm._fetching_bom_for === item_at_trigger) {
			return;
		}
		frm._fetching_bom_for = item_at_trigger;

		frappe.db.get_value(
			"BOM",
			{ item: frm.doc.item, is_default: 1, docstatus: 1 },
			"name"
		).then(({ message }) => {
			if (message && message.name) {
				frm.set_value("bom", message.name);
				return fetch_and_apply_bom(frm, message.name);
			}
			frm.set_value("bom", "");
		}).finally(() => {
			if (frm._fetching_bom_for === item_at_trigger) {
				frm._fetching_bom_for = null;
			}
		});
	},
	qty: calculate_totals,
	inventory_carrying_pct: calculate_other_costs,
	packing_forwarding_pct: calculate_other_costs,
	rejection_pct: calculate_other_costs,
	profit_mode: calculate_totals,
	profit_pct: calculate_totals,
	profit_amount: calculate_totals,
});

function fetch_and_apply_bom(frm, bom) {
	return frappe.call({
		method: "ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_bom_explosion",
		args: { bom: bom, item: frm.doc.item, company: frm.doc.company },
		freeze: true,
		freeze_message: __("Fetching from BOM..."),
	}).then(({ message }) => {
		if (!message) return;

		frm.clear_table("rm_items");
		(message.rm_items || []).forEach((row) => frm.add_child("rm_items", row));

		frm.clear_table("scrap_items");
		(message.scrap_items || []).forEach((row) => frm.add_child("scrap_items", row));

		frm.clear_table("operation_items");
		(message.operation_items || []).forEach((row) => {
			const child = frm.add_child("operation_items", row);
			if (child.workstation && flt(child.time_per_pc_min)) {
				child.rate_per_pc =
					Math.ceil((flt(child.shift_rate_per_min) / flt(child.time_per_pc_min)) * 100) / 100;
			}
		});

		// Keep this in sync with what the server considers "already
		// pulled" — otherwise the first Save would re-explode again and
		// wipe out any edits made in the meantime.
		frm.doc.last_pulled_bom = bom;

		frm.refresh_field("rm_items");
		frm.refresh_field("scrap_items");
		frm.refresh_field("operation_items");
		calculate_rm_totals(frm);

		frappe.show_alert({
			message: __("Fetched RM, Scrap and Operations from {0}", [bom]),
			indicator: "green",
		});
	});
}

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
	scrap_description: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.scrap_description) {
			return;
		}
		frappe.call({
			method: "ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_last_sales_rate_api",
			args: { item_code: row.scrap_description },
		}).then(({ message }) => {
			if (message) {
				row.scrap_rate_per_kg = message;
			}
			frm.refresh_field("scrap_items");
			calculate_scrap_row(frm, cdt, cdn);
		});
	},
	scrap_rate_per_kg: calculate_scrap_row,
	scrap_wt_per_pc: calculate_scrap_row,
	scrap_items_remove: function (frm) {
		calculate_rm_totals(frm);
	},
});

frappe.ui.form.on("Cost Estimation Operation Item", {
	time_per_pc_min: calculate_operation_row,
	shift_rate_per_min: calculate_operation_row,
	rate_per_pc: function (frm) {
		// Rate per Pc is always user-editable — a direct edit here is a
		// manual override, just re-sum totals with whatever was typed.
		calculate_totals(frm);
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
			// Switching to a different machine is a deliberate "start over"
			// for this row — recompute Rate per Pc fresh even if it already
			// had a value (from the previous machine, or a manual override).
			row.rate_per_pc = flt(row.time_per_pc_min)
				? Math.ceil((flt(row.shift_rate_per_min) / flt(row.time_per_pc_min)) * 100) / 100
				: 0;
			if (message.custom_asset_name) {
				frappe.db.get_value("Asset", message.custom_asset_name, "asset_name").then(({ message: asset }) => {
					row.machine_name = asset.asset_name;
					frm.refresh_field("operation_items");
				});
			}
			frm.refresh_field("operation_items");
			calculate_other_costs(frm);
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
	// Triggered by editing Per Min/Pc or Shift Rate per Min — editing an
	// input is a deliberate signal to recalculate, so always recompute here
	// (this overwrites a manual Rate per Pc override, which is expected:
	// the user just changed what it's computed from). A direct edit to
	// Rate per Pc itself goes through a separate handler that doesn't call
	// this function, so that kind of override is untouched by this path.
	if (row.workstation) {
		row.rate_per_pc = flt(row.time_per_pc_min)
			? Math.ceil((flt(row.shift_rate_per_min) / flt(row.time_per_pc_min)) * 100) / 100
			: 0;
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

	frm.doc.total_component_cost_for_qty = flt(frm.doc.total_component_cost) * flt(frm.doc.qty);
	frm.refresh_field("total_component_cost_for_qty");

	render_summary(frm);
}

const CE_SUMMARY_STYLE = `
	<style>
		.ce-summary-tree { width: 100%; font-variant-numeric: tabular-nums; font-size: 14px; }
		.ce-summary-tree .ce-card {
			border: 1px solid var(--border-color); border-radius: var(--border-radius, 8px);
			overflow: hidden; background: var(--fg-color, transparent);
		}
		.ce-summary-tree .ce-row {
			display: flex; align-items: center; justify-content: space-between;
			padding: 11px 20px; gap: 16px;
		}
		.ce-summary-tree .ce-row__label {
			color: var(--text-color); min-width: 0; overflow: hidden; text-overflow: ellipsis;
			white-space: nowrap; display: flex; align-items: center;
		}
		.ce-summary-tree .ce-row__value { color: var(--text-color); white-space: nowrap; font-weight: 500; flex-shrink: 0; }
		.ce-summary-tree .ce-row--muted .ce-row__label,
		.ce-summary-tree .ce-row--muted .ce-row__value { color: var(--text-muted); font-weight: 400; }
		.ce-summary-tree .ce-row--bold .ce-row__label,
		.ce-summary-tree .ce-row--bold .ce-row__value { font-weight: 600; }
		.ce-summary-tree .ce-row--total {
			background: var(--control-bg); font-weight: 600;
			border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color);
		}
		.ce-summary-tree .ce-row--total .ce-row__label,
		.ce-summary-tree .ce-row--total .ce-row__value { font-weight: 600; }
		.ce-summary-tree .ce-node:not(:last-child) { border-bottom: 1px solid var(--border-color); }
		.ce-summary-tree .ce-row--parent { cursor: pointer; list-style: none; }
		.ce-summary-tree .ce-row--parent::-webkit-details-marker { display: none; }
		.ce-summary-tree .ce-row--parent:hover { background: var(--control-bg); }
		.ce-summary-tree .ce-caret {
			display: inline-block; width: 14px; flex-shrink: 0; margin-right: 8px;
			color: var(--text-muted); font-size: 10px; transition: transform 0.15s ease;
		}
		.ce-summary-tree details[open] > summary .ce-caret { transform: rotate(90deg); }
		.ce-summary-tree .ce-node__children {
			margin: 0 20px 10px 34px; padding-left: 16px;
			border-left: 2px solid var(--border-color);
		}
		.ce-summary-tree .ce-node__children .ce-row { padding: 7px 10px; }
		.ce-summary-tree .ce-hero {
			margin-top: 16px; padding: 18px 24px; border-radius: var(--border-radius, 8px);
			background: var(--control-bg); border: 1px solid var(--border-color);
			display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px;
		}
		.ce-summary-tree .ce-hero__label {
			font-size: 12.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em;
		}
		.ce-summary-tree .ce-hero__value {
			font-size: 28px; font-weight: 700; color: var(--text-color);
		}
	</style>
`;

function ce_fmt(value) {
	return "₹" + flt(value).toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function summary_row(label, value, { bold = false, muted = false, is_total = false } = {}) {
	let classes = "ce-row";
	if (muted) classes += " ce-row--muted";
	if (bold) classes += " ce-row--bold";
	if (is_total) classes += " ce-row--total";
	return `
		<div class="${classes}">
			<span class="ce-row__label">${label}</span>
			<span class="ce-row__value">${ce_fmt(value)}</span>
		</div>
	`;
}

function summary_details_row(summary_label, summary_value, child_rows_html, { bold = false } = {}) {
	const classes = "ce-row ce-row--parent" + (bold ? " ce-row--bold" : "");
	return `
		<details class="ce-node">
			<summary class="${classes}">
				<span class="ce-row__label"><span class="ce-caret">▸</span>${summary_label}</span>
				<span class="ce-row__value">${ce_fmt(summary_value)}</span>
			</summary>
			<div class="ce-node__children">
				${child_rows_html}
			</div>
		</details>
	`;
}

function render_summary(frm) {
	const rm_child_rows =
		(frm.doc.rm_items || [])
			.map((r) =>
				summary_row(
					`${r.rm_used || "—"}  (${flt(r.gross_wt_per_pc).toFixed(3)} kg × ${flt(r.rm_rate_per_kg).toFixed(3)})`,
					r.gross_rm_cost_per_pc,
					{ muted: true }
				)
			)
			.join("") || summary_row("No RM rows", 0, { muted: true });

	const scrap_child_rows =
		(frm.doc.scrap_items || [])
			.map((r) =>
				summary_row(
					`${r.scrap_description || "—"}  (${flt(r.scrap_wt_per_pc).toFixed(3)} kg × ${flt(r.scrap_rate_per_kg).toFixed(3)})`,
					r.scrap_price_per_pc,
					{ muted: true }
				)
			)
			.join("") || summary_row("No scrap rows", 0, { muted: true });

	const op_child_rows =
		(frm.doc.operation_items || [])
			.map((r) =>
				summary_row(
					`${r.operation || "—"} — ${r.machine_name || r.workstation || "no machine"}  ` +
						`(${flt(r.shift_rate_per_min).toFixed(3)} ÷ ${flt(r.time_per_pc_min).toFixed(3)} pc/min)`,
					r.rate_per_pc,
					{ muted: true }
				)
			)
			.join("") || summary_row("No operation rows", 0, { muted: true });

	const other_cost_rows = [
		summary_row(
			`Inventory Carrying (${flt(frm.doc.inventory_carrying_pct).toFixed(2)}%)`,
			frm.doc.inventory_carrying_cost,
			{ muted: true }
		),
		summary_row(
			`Packing & Forwarding (${flt(frm.doc.packing_forwarding_pct).toFixed(2)}%)`,
			frm.doc.packing_forwarding_cost,
			{ muted: true }
		),
		summary_row(`Rejection (${flt(frm.doc.rejection_pct).toFixed(2)}%)`, frm.doc.rejection_cost, {
			muted: true,
		}),
	].join("");
	const other_costs_total =
		flt(frm.doc.inventory_carrying_cost) + flt(frm.doc.packing_forwarding_cost) + flt(frm.doc.rejection_cost);

	const body = [
		summary_details_row("Gross RM Cost / Pc", frm.doc.total_gross_rm_cost_per_pc, rm_child_rows),
		summary_details_row("Scrap Recovery / Pc", -flt(frm.doc.total_scrap_price_per_pc), scrap_child_rows),
		summary_row("Net RM Cost / Pc", frm.doc.net_rm_cost_per_pc, { is_total: true }),
		summary_details_row(
			"Total Labour (Operations) Cost / Pc",
			frm.doc.total_labour_cost_per_pc,
			op_child_rows,
			{ bold: true }
		),
		summary_details_row("Other Costs / Pc", other_costs_total, other_cost_rows, { bold: true }),
		summary_row("Total Cost / Pc", frm.doc.total_cost_per_pc, { is_total: true }),
		summary_row(
			"Profit Amount / Pc" +
				(frm.doc.profit_mode === "Percentage" ? ` (${flt(frm.doc.profit_pct).toFixed(2)}%)` : " (flat)"),
			frm.doc.profit_amount,
			{ muted: true }
		),
		summary_row("Total Component Cost / Pc", frm.doc.total_component_cost, { is_total: true }),
	].join("");

	frm.doc.summary_html = `
		${CE_SUMMARY_STYLE}
		<div class="ce-summary-tree">
			<div class="ce-card">
				${body}
			</div>
			<div class="ce-hero">
				<div class="ce-hero__label">Total Component Cost &times; Qty (${flt(frm.doc.qty).toFixed(3)})</div>
				<div class="ce-hero__value">${ce_fmt(frm.doc.total_component_cost_for_qty)}</div>
			</div>
		</div>
	`;

	if (frm.fields_dict.summary_html) {
		frm.fields_dict.summary_html.$wrapper.html(frm.doc.summary_html);
	}
}
