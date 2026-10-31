// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

// FUTURE USE — currently hidden (2026-10-31).
// This doctype is not needed in the system right now, so all role permissions
// were removed from quotation_cost_estimation.json: only Administrator can
// open it and it does not appear for any other user. The code is kept as-is
// for a future quotation-costing flow (costing new parts that have no Item/BOM
// yet). To re-enable: add role permissions back in the JSON (previously System
// Manager, Manufacturing Manager, Manufacturing User) and run `bench migrate`.

// Same costing as Cost Estimation, but Part/RM/Scrap are typed by hand (no
// Item/BOM links) and every figure is per piece — only the final total is
// multiplied by Quantity. Keep formulas in sync with
// quotation_cost_estimation.py.

frappe.ui.form.on("Quotation Cost Estimation", {
	refresh: calculate_rm_totals,
	qty: calculate_totals,
	inventory_carrying_pct: calculate_other_costs,
	packing_forwarding_pct: calculate_other_costs,
	rejection_pct: calculate_other_costs,
	profit_mode: calculate_totals,
	profit_pct: calculate_totals,
	profit_amount: calculate_totals,
});

frappe.ui.form.on("Quotation Cost Estimation RM Item", {
	rm_name: calculate_rm_totals,
	rm_code: calculate_rm_totals,
	rm_rate_per_kg: calculate_rm_row,
	gross_wt_per_pc: calculate_rm_row,
	rm_items_remove: calculate_rm_totals,
});

frappe.ui.form.on("Quotation Cost Estimation Scrap Item", {
	scrap_name: calculate_rm_totals,
	scrap_code: calculate_rm_totals,
	scrap_rate_per_kg: calculate_scrap_row,
	scrap_wt_per_pc: calculate_scrap_row,
	scrap_items_remove: calculate_rm_totals,
});

frappe.ui.form.on("Quotation Cost Estimation Operation Item", {
	operation: calculate_totals,
	time_per_pc_min: calculate_operation_row,
	shift_rate_per_min: calculate_operation_row,
	// A direct edit to Rate per Pc is a manual override — just re-sum.
	rate_per_pc: calculate_totals,
	workstation: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.workstation) {
			row.machine_name = "";
			frm.refresh_field("operation_items");
			calculate_totals(frm);
			return;
		}
		frappe.db
			.get_value("Workstation", row.workstation, ["custom_cost_per_min", "custom_asset_name"])
			.then(({ message }) => {
				row.shift_rate_per_min = message.custom_cost_per_min;
				row.rate_per_pc = compute_rate_per_pc(row.shift_rate_per_min, row.time_per_pc_min);
				row.machine_name = "";
				if (message.custom_asset_name) {
					frappe.db.get_value("Asset", message.custom_asset_name, "asset_name").then(({ message: asset }) => {
						row.machine_name = asset.asset_name;
						frm.refresh_field("operation_items");
						render_summary(frm);
					});
				}
				frm.refresh_field("operation_items");
				calculate_other_costs(frm);
			});
	},
	operation_items_remove: calculate_totals,
});

function compute_rate_per_pc(shift_rate_per_min, time_per_pc_min) {
	if (!flt(time_per_pc_min)) {
		return 0;
	}
	return flt(shift_rate_per_min) / flt(time_per_pc_min);
}

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
	const total_gross_rm_cost = (frm.doc.rm_items || []).reduce((s, r) => s + flt(r.gross_rm_cost_per_pc), 0);
	const total_scrap_price = (frm.doc.scrap_items || []).reduce((s, r) => s + flt(r.scrap_price_per_pc), 0);

	frm.doc.total_gross_rm_cost_per_pc = total_gross_rm_cost;
	frm.doc.total_scrap_price_per_pc = total_scrap_price;
	frm.doc.net_rm_cost_per_pc = total_gross_rm_cost - total_scrap_price;
	frm.refresh_fields(["total_gross_rm_cost_per_pc", "total_scrap_price_per_pc", "net_rm_cost_per_pc"]);

	calculate_other_costs(frm);
}

function calculate_operation_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	// Editing an input recomputes Rate per Pc (overwrites a manual override).
	if (row.workstation) {
		row.rate_per_pc = compute_rate_per_pc(row.shift_rate_per_min, row.time_per_pc_min);
	}
	frm.refresh_field("operation_items");
	calculate_other_costs(frm);
}

function get_total_labour_cost(frm) {
	frm.doc.total_labour_cost_per_pc = (frm.doc.operation_items || []).reduce((s, r) => s + flt(r.rate_per_pc), 0);
	frm.refresh_field("total_labour_cost_per_pc");
	return frm.doc.total_labour_cost_per_pc;
}

function get_base_for_pct(frm) {
	return flt(frm.doc.net_rm_cost_per_pc) + get_total_labour_cost(frm);
}

function calculate_other_costs(frm) {
	const base_for_pct = get_base_for_pct(frm);
	frm.doc.inventory_carrying_cost =
		(flt(frm.doc.total_gross_rm_cost_per_pc) * flt(frm.doc.inventory_carrying_pct)) / 100;
	frm.doc.packing_forwarding_cost = (base_for_pct * flt(frm.doc.packing_forwarding_pct)) / 100;
	frm.doc.rejection_cost = (base_for_pct * flt(frm.doc.rejection_pct)) / 100;
	frm.refresh_fields(["inventory_carrying_cost", "packing_forwarding_cost", "rejection_cost"]);

	calculate_totals(frm);
}

function calculate_totals(frm) {
	const base_for_pct = get_base_for_pct(frm);

	frm.doc.total_cost_per_pc =
		base_for_pct +
		flt(frm.doc.inventory_carrying_cost) +
		flt(frm.doc.packing_forwarding_cost) +
		flt(frm.doc.rejection_cost);

	if (frm.doc.profit_mode === "Percentage") {
		frm.doc.profit_amount = (base_for_pct * flt(frm.doc.profit_pct)) / 100;
	}

	frm.doc.total_component_cost = flt(frm.doc.total_cost_per_pc) + flt(frm.doc.profit_amount);
	frm.doc.total_component_cost_for_qty = flt(frm.doc.total_component_cost) * (flt(frm.doc.qty) || 1);
	frm.refresh_fields(["total_cost_per_pc", "profit_amount", "total_component_cost", "total_component_cost_for_qty"]);

	render_summary(frm);
}

const QCE_SUMMARY_STYLE = `
	<style>
		.ce-summary-tree { width: 100%; font-variant-numeric: tabular-nums; font-size: 14px; }
		.ce-summary-tree .ce-card {
			border: 1px solid var(--border-color); border-radius: var(--border-radius, 8px);
			overflow: hidden; background: var(--fg-color, transparent);
		}
		.ce-summary-tree .ce-row {
			display: flex; align-items: center; justify-content: space-between;
			padding: 11px 20px; gap: 16px; min-width: 0;
		}
		.ce-summary-tree .ce-row__label {
			color: var(--text-color); min-width: 0; overflow: hidden; text-overflow: ellipsis;
			white-space: nowrap; display: flex; align-items: center; flex: 1 1 auto;
		}
		.ce-summary-tree .ce-row__value {
			color: var(--text-color); white-space: nowrap; font-weight: 500; flex: 0 0 auto;
		}
		.ce-summary-tree .ce-row--muted .ce-row__label,
		.ce-summary-tree .ce-row--muted .ce-row__value { color: var(--text-muted); font-weight: 400; }
		.ce-summary-tree .ce-row--bold .ce-row__label,
		.ce-summary-tree .ce-row--bold .ce-row__value { font-weight: 600; }
		/* Plain caption line inside a breakdown (no ₹ value) — the
		   explanatory sentence is longer than a normal row label, so let it
		   wrap onto multiple lines instead of being ellipsis-truncated. */
		.ce-summary-tree .ce-row--note .ce-row__label {
			white-space: normal; font-style: italic; font-size: 12.5px; line-height: 1.4;
		}
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
		/* Item/group nodes (a rollup of everything nested inside them) get an
		   accent color + bold weight so they read as a subtotal at a glance,
		   distinct from a plain (muted) single-operation cost line. */
		.ce-summary-tree .ce-row--item-node .ce-row__label,
		.ce-summary-tree .ce-row--item-node .ce-row__value {
			color: var(--blue-600, #2490ef); font-weight: 600;
		}
		.ce-summary-tree .ce-caret {
			display: inline-block; width: 14px; flex-shrink: 0; margin-right: 8px;
			color: var(--text-muted); font-size: 10px; transition: transform 0.15s ease;
		}
		.ce-summary-tree details[open] > summary .ce-caret { transform: rotate(90deg); }
		/* Each nesting level narrows the row (margin-right grows with depth
		   too, not just margin-left) so a row's ₹ value sits close to its own
		   label at that depth, instead of every row's value lining up flush
		   against the outermost card edge regardless of how deep it is. */
		.ce-summary-tree .ce-node__children {
			margin: 0 14px 10px 26px; padding-left: 14px;
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

function qce_fmt(value) {
	return "₹" + flt(value).toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function summary_row(label, value, { muted = false, is_total = false } = {}) {
	let classes = "ce-row";
	if (muted) classes += " ce-row--muted";
	if (is_total) classes += " ce-row--total";
	return `
		<div class="${classes}">
			<span class="ce-row__label">${label}</span>
			<span class="ce-row__value">${qce_fmt(value)}</span>
		</div>
	`;
}

function summary_details_row(summary_label, summary_value, child_rows_html, { bold = false } = {}) {
	const classes = "ce-row ce-row--parent" + (bold ? " ce-row--bold" : "");
	return `
		<details class="ce-node">
			<summary class="${classes}">
				<span class="ce-row__label"><span class="ce-caret">▸</span>${summary_label}</span>
				<span class="ce-row__value">${qce_fmt(summary_value)}</span>
			</summary>
			<div class="ce-node__children">
				${child_rows_html}
			</div>
		</details>
	`;
}

function rm_scrap_label(code, name, wt, rate) {
	const label = [code, name].filter(Boolean).map(frappe.utils.escape_html).join(" — ") || "—";
	return `${label}  (${flt(wt).toFixed(3)} kg × ${flt(rate).toFixed(3)})`;
}

function render_summary(frm) {
	if (!frm.fields_dict.summary_html) {
		return;
	}
	const esc = frappe.utils.escape_html;

	const rm_child_rows =
		(frm.doc.rm_items || [])
			.map((r) =>
				summary_row(rm_scrap_label(r.rm_code, r.rm_name, r.gross_wt_per_pc, r.rm_rate_per_kg), r.gross_rm_cost_per_pc, {
					muted: true,
				})
			)
			.join("") || summary_row("No RM rows", 0, { muted: true });

	const scrap_child_rows =
		(frm.doc.scrap_items || [])
			.map((r) =>
				summary_row(
					rm_scrap_label(r.scrap_code, r.scrap_name, r.scrap_wt_per_pc, r.scrap_rate_per_kg),
					r.scrap_price_per_pc,
					{ muted: true }
				)
			)
			.join("") || summary_row("No scrap rows", 0, { muted: true });

	const op_child_rows =
		(frm.doc.operation_items || [])
			.map((r) =>
				summary_row(
					`${esc(r.operation || "—")} — ${esc(r.machine_name || r.workstation || "no machine")}  ` +
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
		summary_row(`Rejection (${flt(frm.doc.rejection_pct).toFixed(2)}%)`, frm.doc.rejection_cost, { muted: true }),
	].join("");
	const other_costs_total =
		flt(frm.doc.inventory_carrying_cost) + flt(frm.doc.packing_forwarding_cost) + flt(frm.doc.rejection_cost);

	const body = [
		summary_details_row("Gross RM Cost / Pc", frm.doc.total_gross_rm_cost_per_pc, rm_child_rows),
		summary_details_row("Scrap Recovery / Pc", -flt(frm.doc.total_scrap_price_per_pc), scrap_child_rows),
		summary_row("Net RM Cost / Pc", frm.doc.net_rm_cost_per_pc, { is_total: true }),
		summary_details_row("Total Labour (Operations) Cost / Pc", frm.doc.total_labour_cost_per_pc, op_child_rows, {
			bold: true,
		}),
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

	frm.fields_dict.summary_html.$wrapper.html(`
		${QCE_SUMMARY_STYLE}
		<div class="ce-summary-tree">
			<div class="ce-card">
				${body}
			</div>
			<div class="ce-hero">
				<div class="ce-hero__label">Total Component Cost &times; Qty (${flt(frm.doc.qty).toFixed(3)})</div>
				<div class="ce-hero__value">${qce_fmt(frm.doc.total_component_cost_for_qty)}</div>
			</div>
		</div>
	`);
}
