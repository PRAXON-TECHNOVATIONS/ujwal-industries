// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cost Estimation", {
	setup: function (frm) {
		frm.set_query("item", function () {
			return {
				query: "ujwal_industries.api.link_queries.item_query",
				filters: {
					is_fixed_asset: 0,
				},
			};
		});

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
		reset_stale_grid_columns(frm);
		add_sync_buttons(frm);
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
	qty: function (frm) {
		// RM/Scrap weights scale with Quantity (see explode_bom_tree's
		// qty_multiplier) — re-pull from the BOM so Gross Wt/Pc reflects the
		// new Quantity, same as picking a different BOM does. Operations are
		// untouched by this re-pull's qty_multiplier (only RM/Scrap use it),
		// so a manual Rate/Pc override there survives via the usual sync
		// merge semantics — but a live re-fetch (not sync) always refreshes,
		// same as the existing BOM-pick behavior.
		if (frm.doc.bom) {
			fetch_and_apply_bom(frm, frm.doc.bom);
		} else {
			calculate_totals(frm);
		}
	},
	inventory_carrying_pct: calculate_other_costs,
	packing_forwarding_pct: calculate_other_costs,
	rejection_pct: calculate_other_costs,
	profit_mode: calculate_totals,
	profit_pct: calculate_totals,
	profit_amount: calculate_totals,
});

const GRID_CHILD_DOCTYPES = [
	"Cost Estimation Operation Item",
	"Cost Estimation RM Item",
	"Cost Estimation Scrap Item",
];

function add_sync_buttons(frm) {
	if (frm.is_new() || !frm.doc.bom) return;

	function run_sync(method, label) {
		frappe.call({
			method: `ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.${method}`,
			args: { cost_estimation: frm.doc.name },
			freeze: true,
			freeze_message: __("Syncing {0}...", [label]),
		}).then(() => {
			frappe.show_alert({ message: __("{0} synced with BOM", [label]), indicator: "green" });
			frm.reload_doc();
		});
	}

	// A single "Sync" group button with the combined sync as its own click
	// target, and the 3 individual table syncs as items underneath it — per
	// the user's ask for "3 buttons under a common sync button".
	frm.add_custom_button(__("Sync All"), () => run_sync("sync_all_tables", __("All tables")), __("Sync"));
	frm.add_custom_button(__("Sync RM"), () => run_sync("sync_rm_items", __("RM")), __("Sync"));
	frm.add_custom_button(__("Sync Scrap"), () => run_sync("sync_scrap_items", __("Scrap")), __("Sync"));
	frm.add_custom_button(
		__("Sync Operations"),
		() => run_sync("sync_operation_items", __("Operations")),
		__("Sync")
	);
}

function reset_stale_grid_columns(frm) {
	// Runs once per page load (not once per refresh() call) — the fix below
	// itself triggers frm.refresh() to redraw the grids with the corrected
	// layout, so without this guard that redraw would re-enter this
	// function and could loop if the save round-trip is ever slow to land
	// in frappe.model.user_settings.
	if (frm._grid_columns_checked) return;
	frm._grid_columns_checked = true;

	// A user's grid column layout (which fields show, in what order) is
	// saved per child-table doctype in "User Settings" → GridView and, once
	// saved, REPLACES the doctype's own in_list_view defaults entirely
	// (frappe/public/js/frappe/form/grid.js: setup_user_defined_columns) —
	// it does not merge in fields added to the doctype after that save. So
	// a layout saved before `item`/`tool`/`no_of_cavities` (Operations) or
	// `item_name`/`bom` (RM/Scrap) existed permanently hides them for that
	// user, even though the doctype itself already marks them
	// in_list_view=1. Detect a saved layout that's missing a field the
	// doctype currently wants shown, and clear just that one entry so the
	// grid falls back to (and re-saves, next time the user reorders columns)
	// the current default column set.
	// Work on our own copy — grid_view_settings is the live cache object
	// (frappe.model.user_settings[frm.doctype].GridView), and mutating it in
	// place before frappe.model.user_settings.update() re-fetches/overwrites
	// it would make `changed` detection unreliable on a second call.
	const grid_view_settings = Object.assign({}, frappe.get_user_settings(frm.doctype, "GridView") || {});
	let changed = false;

	GRID_CHILD_DOCTYPES.forEach((child_doctype) => {
		const saved_columns = grid_view_settings[child_doctype];
		if (!saved_columns || !saved_columns.length) return;

		const saved_fieldnames = new Set(saved_columns.map((c) => c.fieldname));
		const meta = frappe.get_meta(child_doctype);
		if (!meta) return;

		const expected_fieldnames = meta.fields.filter((f) => f.in_list_view).map((f) => f.fieldname);
		const is_stale = expected_fieldnames.some((fieldname) => !saved_fieldnames.has(fieldname));

		if (is_stale) {
			delete grid_view_settings[child_doctype];
			changed = true;
		}
	});

	if (changed) {
		// save() merges into the existing GridView object (via $.extend),
		// which would leave the just-deleted key present — go through
		// update() directly so the full corrected object actually replaces
		// what's cached and saved server-side.
		const full_settings = Object.assign({}, frappe.model.user_settings[frm.doctype] || {});
		full_settings.GridView = grid_view_settings;
		frappe.model.user_settings.update(frm.doctype, full_settings).then(() => {
			frm.refresh();
		});
	}
}

function fetch_and_apply_bom(frm, bom) {
	return frappe.call({
		method: "ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_bom_explosion",
		args: { bom: bom, item: frm.doc.item, company: frm.doc.company, qty: flt(frm.doc.qty) || 1 },
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
				child.rate_per_pc = compute_operation_rate(child);
			}
		});

		// Keep this in sync with what the server considers "already
		// pulled" — otherwise the first Save would re-explode again and
		// wipe out any edits made in the meantime.
		frm.doc.last_pulled_bom = bom;
		frm.doc.last_pulled_qty = flt(frm.doc.qty) || 1;
		frm.doc.item_tree_json = JSON.stringify(message.item_tree_edges || []);

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
		frappe.db.get_value("Item", row.rm_used, ["last_purchase_rate", "item_name"]).then(({ message }) => {
			if (message.last_purchase_rate) {
				row.rm_rate_per_kg = message.last_purchase_rate;
			}
			row.item_name = message.item_name;
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
		frappe.db.get_value("Item", row.scrap_description, "item_name").then(({ message }) => {
			row.item_name = message.item_name;
			frm.refresh_field("scrap_items");
		});
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
	no_of_cavities: calculate_operation_row,
	qty_multiplier: calculate_operation_row,
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
			row.rate_per_pc = compute_operation_rate(row);
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
	tool: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.tool) {
			row.no_of_cavities = 0;
			frm.refresh_field("operation_items");
			calculate_operation_row(frm, cdt, cdn);
			return;
		}
		// Picking a different tool is a deliberate "start over" for cavity
		// count — refetch even if the row already had one set.
		frappe.db.get_value("Asset", row.tool, "custom_no_of_cavities").then(({ message }) => {
			row.no_of_cavities = message.custom_no_of_cavities;
			frm.refresh_field("operation_items");
			calculate_operation_row(frm, cdt, cdn);
		});
	},
	operation_items_remove: function (frm) {
		calculate_totals(frm);
	},
});

function compute_rate_per_pc(shift_rate_per_min, time_per_pc_min, no_of_cavities, qty_multiplier) {
	// Mirrors compute_rate_per_pc in cost_estimation.py — keep both in sync.
	if (!flt(time_per_pc_min)) {
		return 0;
	}
	let rate = flt(shift_rate_per_min) / flt(time_per_pc_min);
	const cavities = flt(no_of_cavities);
	if (cavities) {
		rate = rate / cavities;
	}
	const multiplier = flt(qty_multiplier) || 1;
	if (multiplier !== 1) {
		rate = rate * multiplier;
	}
	return rate;
}

function compute_assembly_breakdown_rate(shift_rate_per_min, time_per_pc_min, no_of_cavities, breakdown) {
	// Mirrors compute_assembly_breakdown_rate in cost_estimation.py — keep
	// both in sync. Sums (shared per-cavity base rate × each sub-part's own
	// qty_multiplier) for a single Assembly row that consumes several
	// manufactured sub-parts.
	const base_rate = compute_rate_per_pc(shift_rate_per_min, time_per_pc_min, no_of_cavities);
	const total = (breakdown || []).reduce((sum, entry) => sum + base_rate * flt(entry.qty_multiplier), 0);
	return total;
}

function compute_operation_rate(row) {
	// Dispatches to whichever formula applies to this row — a multi-
	// component Assembly row (assembly_breakdown_json set) sums per
	// sub-part, everything else uses the single qty_multiplier formula.
	if (row.assembly_breakdown_json) {
		let breakdown = [];
		try {
			breakdown = JSON.parse(row.assembly_breakdown_json);
		} catch (e) {
			breakdown = [];
		}
		return compute_assembly_breakdown_rate(
			row.shift_rate_per_min,
			row.time_per_pc_min,
			row.no_of_cavities,
			breakdown
		);
	}
	return compute_rate_per_pc(row.shift_rate_per_min, row.time_per_pc_min, row.no_of_cavities, row.qty_multiplier);
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
	// Triggered by editing Per Min/Pc, Shift Rate per Min or No of Cavities —
	// editing an input is a deliberate signal to recalculate, so always
	// recompute here (this overwrites a manual Rate per Pc override, which is
	// expected: the user just changed what it's computed from). A direct edit
	// to Rate per Pc itself goes through a separate handler that doesn't call
	// this function, so that kind of override is untouched by this path.
	if (row.workstation) {
		row.rate_per_pc = compute_operation_rate(row);
	}
	frm.refresh_field("operation_items");
	calculate_other_costs(frm);
}

function get_base_for_pct(frm, total_labour_cost) {
	// net_rm_cost_per_pc already carries the Quantity scaling (RM/Scrap
	// weights are exploded with qty_multiplier = Quantity, see
	// explode_bom_tree / cost_estimation.py::_base_for_pct — keep both in
	// sync), but total_labour_cost_per_pc is intentionally still a true
	// per-single-piece figure, so it's multiplied by Quantity here, once,
	// before combining with RM/Scrap.
	return flt(frm.doc.net_rm_cost_per_pc) + total_labour_cost * (flt(frm.doc.qty) || 1);
}

function calculate_other_costs(frm) {
	const base_for_pct = get_base_for_pct(frm, get_total_labour_cost(frm));

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
	const base_for_pct = get_base_for_pct(frm, total_labour_cost);

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

	// total_cost_per_pc/total_component_cost are already computed on the
	// "for this Quantity" basis via get_base_for_pct() above, so the final
	// total is NOT multiplied by Quantity again here (keep in sync with
	// cost_estimation.py::calculate_totals).
	frm.doc.total_component_cost_for_qty = flt(frm.doc.total_component_cost);
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

function note_row(text) {
	// A plain explanatory caption line with no ₹ value — for context text
	// inside an expanded breakdown that would be misleading rendered as a
	// ₹0.000 cost row via summary_row().
	return `
		<div class="ce-row ce-row--muted ce-row--note">
			<span class="ce-row__label">${text}</span>
		</div>
	`;
}

function summary_details_row(summary_label, summary_value, child_rows_html, { bold = false, item_node = false } = {}) {
	let classes = "ce-row ce-row--parent";
	if (bold) classes += " ce-row--bold";
	if (item_node) classes += " ce-row--item-node";
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

function operation_leaf_row(r) {
	const qty_multiplier = flt(r.qty_multiplier);
	const label =
		`${r.operation || "—"} — ${r.machine_name || r.workstation || "no machine"}  ` +
		`(${flt(r.shift_rate_per_min).toFixed(3)} ÷ ${flt(r.time_per_pc_min).toFixed(3)} pc/min` +
		`${flt(r.no_of_cavities) ? ` ÷ ${flt(r.no_of_cavities).toFixed(0)} cav` : ""}` +
		`${qty_multiplier && qty_multiplier !== 1 ? ` × ${qty_multiplier.toFixed(3)} qty` : ""})`;

	if (!r.assembly_breakdown_json) {
		return summary_row(label, r.rate_per_pc, { muted: true });
	}

	// Single Assembly row costing several sub-parts — expand into the
	// per-sub-part contributions so it's clear how the one row's Rate/Pc
	// was built up, without turning it into several grid rows. The label
	// itself flags "N components" so it's visibly different from a plain
	// operation row BEFORE it's expanded, not just once opened.
	let breakdown = [];
	try {
		breakdown = JSON.parse(r.assembly_breakdown_json);
	} catch (e) {
		breakdown = [];
	}
	const base_rate = compute_rate_per_pc(r.shift_rate_per_min, r.time_per_pc_min, r.no_of_cavities);
	const total_qty = breakdown.reduce((sum, entry) => sum + flt(entry.qty_multiplier), 0);

	const label_with_hint =
		`${label}  — ${breakdown.length} components, ${total_qty.toFixed(0)} pcs assembled per unit ` +
		`(click to see per-part cost)`;

	const explainer_row = note_row(
		`One Assembly step, done once — its Rate/Pc (${ce_fmt(r.rate_per_pc)}) is this operation's ` +
			`per-piece rate (${flt(base_rate).toFixed(3)}/pc) × how many of each part go into one finished unit, summed:`
	);

	const breakdown_rows =
		explainer_row +
		breakdown
			.map((entry) => {
				const name_part =
					entry.item_name && entry.item_name !== entry.item ? ` — ${entry.item_name}` : "";
				const qty = flt(entry.qty_multiplier);
				return summary_row(
					`${entry.item || "—"}${name_part}: ${qty.toFixed(0)} pcs × ${flt(base_rate).toFixed(3)}/pc`,
					base_rate * qty,
					{ muted: true }
				);
			})
			.join("");
	return summary_details_row(label_with_hint, r.rate_per_pc, breakdown_rows);
}

function item_label(frm, item_code) {
	if (!item_code) return "—";
	frm._item_name_cache = frm._item_name_cache || {};
	if (item_code in frm._item_name_cache) {
		const name = frm._item_name_cache[item_code];
		return name && name !== item_code ? `${item_code} — ${name}` : item_code;
	}
	// Not cached yet — kick off a fetch and re-render once it lands rather
	// than blocking this render (render_summary must stay synchronous, it's
	// called on every field change).
	frm._item_name_cache[item_code] = null;
	frappe.db.get_value("Item", item_code, "item_name").then(({ message }) => {
		frm._item_name_cache[item_code] = (message && message.item_name) || item_code;
		render_summary(frm);
	});
	return item_code;
}

function build_operation_tree_html(frm, operation_items, item_tree_edges) {
	// Mirrors build_operation_tree_html in cost_estimation.py — keep both in
	// sync. Renders Operations as a nested BOM tree — one expandable node per
	// item, holding that item's own operation rows plus (nested inside) the
	// node of every item its BOM consumes.
	//
	// item_tree_edges — [item, parent_item] pairs for EVERY item the BOM walk
	// visited (from frm.doc.item_tree_json) — is the source of truth for
	// parent linkage, since a pure-container assembly (sub-items have
	// operations, it has none of its own) never appears as an `item` on any
	// operation row and so can't otherwise be placed in the tree correctly.
	// Falls back to each row's own `parent_item` for any item missing from
	// the edges (e.g. older records saved before this field existed, or
	// hand-typed rows).
	const items = operation_items || [];
	const untagged = items.filter((r) => !r.item);
	const tagged = items.filter((r) => r.item);

	if (!tagged.length && !untagged.length) {
		return summary_row("No operation rows", 0, { muted: true });
	}

	const itemParent = {};
	(item_tree_edges || []).forEach(([item, parent]) => {
		if (item && !(item in itemParent)) itemParent[item] = parent || "";
	});

	const rowsByItem = {};
	const itemOrder = [];
	tagged.forEach((r) => {
		if (!rowsByItem[r.item]) {
			rowsByItem[r.item] = [];
			itemOrder.push(r.item);
		}
		rowsByItem[r.item].push(r);
		if (!(r.item in itemParent)) {
			itemParent[r.item] = r.parent_item || "";
		}
	});

	// A pure-container assembly is known only from item_tree_edges, never
	// from a row's own `item` — add it to itemOrder so it gets a node in the
	// tree instead of its children being orphaned to root.
	Object.keys(itemParent).forEach((item) => {
		if (!(item in rowsByItem)) {
			rowsByItem[item] = [];
			itemOrder.push(item);
		}
	});

	const childrenByParent = {};
	itemOrder.forEach((item) => {
		const parent = itemParent[item] || "";
		if (!childrenByParent[parent]) childrenByParent[parent] = [];
		childrenByParent[parent].push(item);
	});

	const knownItems = new Set(itemOrder);
	const rootSeen = new Set();
	const roots = itemOrder.filter((item) => {
		const parent = itemParent[item];
		const isRoot = !parent || !knownItems.has(parent);
		if (!isRoot || rootSeen.has(item)) return false;
		rootSeen.add(item);
		return true;
	});

	function itemSubtotal(item, visited) {
		if (visited.has(item)) return 0;
		visited.add(item);
		let total = (rowsByItem[item] || []).reduce((sum, r) => sum + flt(r.rate_per_pc), 0);
		(childrenByParent[item] || []).forEach((child) => {
			total += itemSubtotal(child, visited);
		});
		return total;
	}

	// A pure-RM item (no operation performed on it, no sub-items of its own
	// with operations) contributes nothing to labour cost and would only be
	// an empty, always-zero node — RM cost already has its own section above,
	// so prune these rather than duplicate/clutter. An assembly (SFG/FG) with
	// operation-bearing children is always kept, even with no operation of
	// its own — only truly empty branches drop.
	function hasOperations(item, visited) {
		if (visited.has(item)) return false;
		visited.add(item);
		if ((rowsByItem[item] || []).length) return true;
		return (childrenByParent[item] || []).some((child) => hasOperations(child, new Set(visited)));
	}

	function renderItemNode(item, visited) {
		if (visited.has(item) || !hasOperations(item, new Set())) return "";
		visited.add(item);
		const ownRows = (rowsByItem[item] || []).map(operation_leaf_row).join("");
		const childNodes = (childrenByParent[item] || []).map((child) => renderItemNode(child, visited)).join("");
		return summary_details_row(item_label(frm, item), itemSubtotal(item, new Set()), ownRows + childNodes, {
			item_node: true,
		});
	}

	const visited = new Set();
	const treeHtml = roots.map((item) => renderItemNode(item, visited)).join("");
	const untaggedHtml = untagged.map(operation_leaf_row).join("");

	return treeHtml + untaggedHtml;
}

function rm_scrap_label(item_code, item_name, bom, wt, rate) {
	const namePart = item_name && item_name !== item_code ? ` — ${item_name}` : "";
	const bomPart = bom ? `  [${bom}]` : "";
	return `${item_code || "—"}${namePart}${bomPart}  (${flt(wt).toFixed(3)} kg × ${flt(rate).toFixed(3)})`;
}

function render_summary(frm) {
	const rm_child_rows =
		(frm.doc.rm_items || [])
			.map((r) =>
				summary_row(
					rm_scrap_label(r.rm_used, r.item_name, r.bom, r.gross_wt_per_pc, r.rm_rate_per_kg),
					r.gross_rm_cost_per_pc,
					{ muted: true }
				)
			)
			.join("") || summary_row("No RM rows", 0, { muted: true });

	const scrap_child_rows =
		(frm.doc.scrap_items || [])
			.map((r) =>
				summary_row(
					rm_scrap_label(r.scrap_description, r.item_name, r.bom, r.scrap_wt_per_pc, r.scrap_rate_per_kg),
					r.scrap_price_per_pc,
					{ muted: true }
				)
			)
			.join("") || summary_row("No scrap rows", 0, { muted: true });

	let item_tree_edges = [];
	if (frm.doc.item_tree_json) {
		try {
			item_tree_edges = JSON.parse(frm.doc.item_tree_json);
		} catch (e) {
			item_tree_edges = [];
		}
	}
	const op_child_rows = build_operation_tree_html(frm, frm.doc.operation_items, item_tree_edges);

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
