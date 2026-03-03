// Production Plan Importer — Handsontable integration
// Loads Production Plan data directly from DB (selected from PP list view).
// After loading, _actual_* shadow fields capture the DB baseline for comparison (red = differs from DB).
// Left panel  : vertical tabs, one per Production Plan.
// Right panel : FG Items / Sub Assembly / MR Items tabs with Handsontable grids.
// Apply       : calls save_managed_dates for each PP (direct DB write, bypasses hooks).

const _HOT_ASSETS = [
	"/assets/ujwal_industries/js/vendor/handsontable.full.min.js",
	"/assets/ujwal_industries/css/vendor/handsontable.full.min.css",
	"/assets/ujwal_industries/css/production_plan_importer.css",
];

// ─── Module state ──────────────────────────────────────────────────────────
let _pp_data       = {};   // { ppName: { po_items, sfg_items, mr_items } }
let _pp_use_excel  = {};   // { ppName: bool } — true = view-only mode (readonly grids); false = edit mode
let _pp_imported   = {};   // { ppName: { ok: bool, error?: str } } — set after Apply
let _pp_has_edits  = {};   // { ppName: true } — PP has unsaved HOT edits
let _apply_btn     = null; // jQuery ref to our Apply button (NOT page.btn_primary)
let _current_pp    = null; // active PP tab
let _current_sec   = "fg"; // active section tab: fg | sfg | mr
let _hot_fg        = null;
let _hot_sfg       = null;
let _hot_mr        = null;
let _frm_ref       = null; // reference to frm for layout lookups
let _supplier_cache = {}; // { item_code: ["Supplier A", ...] } — prefetched on load

// Cross-table linkage highlight: { fg: Set<rowIdx>, sfg: Set<rowIdx>, mr: Set<rowIdx> }
let _linked_rows = { fg: new Set(), sfg: new Set(), mr: new Set() };

// Active shift type document (fetched when _opt_shift_type changes)
let _shift_details = null;

// Change-log flush timer + buffer (debounce before sending to server)
let _log_flush_timer    = null;
let _pending_log_entries = [];

// Edit-mode global options (shared across all PPs, reset on new load)
let _opt_shift_wise = false; // enable_shift_wise_scheduling
let _opt_backdated  = false; // allow_backdated_planned_start_date
let _opt_shift_type = "";    // selected shift type name
let _shift_types    = [];    // all Shift Type names fetched once

// ─── Form events ───────────────────────────────────────────────────────────
frappe.ui.form.on("Production Plan Importer", {
	refresh(frm) {
		_frm_ref = frm;

		frm.clear_custom_buttons();
		_apply_btn = frm.add_custom_button(__("Apply to Production Plan"), () => {
			_apply_to_pp();
		}).addClass("btn-primary");

		frappe.require(_HOT_ASSETS, () => {
			_build_layout(frm);
			if (frm.doc.production_plans) {
				_load_from_db(frm.doc.production_plans);
			}
		});
	},
});

// ─── Layout scaffold ───────────────────────────────────────────────────────
function _build_layout(frm) {
	// Destroy stale HOT instances before the DOM is replaced (navigation back to this page).
	if (_hot_fg)  { try { _hot_fg.destroy();  } catch(e) {} _hot_fg  = null; }
	if (_hot_sfg) { try { _hot_sfg.destroy(); } catch(e) {} _hot_sfg = null; }
	if (_hot_mr)  { try { _hot_mr.destroy();  } catch(e) {} _hot_mr  = null; }
	_current_sec  = "fg"; // Reset section on page reload
	_pp_imported  = {};   // Clear import state — will be re-fetched from server
	_pp_has_edits = {};   // Clear edit tracking
	_apply_btn    = null; // Will be re-set by next refresh()

	const $root = frm.fields_dict.importer_layout.$wrapper;
	$root.html(`
		<div class="ppi-container">

			<!-- ── LEFT SIDEBAR ── -->
			<div class="ppi-left" id="ppi-pp-list">
				<div class="ppi-left-header">
					<svg width="12" height="12" viewBox="0 0 16 16" fill="none">
						<rect x="1" y="1" width="6" height="6" rx="1.5" fill="white"/>
						<rect x="9" y="1" width="6" height="6" rx="1.5" fill="white"/>
						<rect x="1" y="9" width="6" height="6" rx="1.5" fill="white"/>
						<rect x="9" y="9" width="6" height="6" rx="1.5" fill="white"/>
					</svg>
					${__("Production Plans")}
				</div>
				<div class="ppi-pp-tabs-wrap" id="ppi-pp-tabs">
					<div class="ppi-empty-hint">${__("Select Production Plans from list view to load here")}</div>
				</div>
			</div>

			<!-- ── RIGHT PANEL ── -->
			<div class="ppi-right">

				<!-- PP info bar -->
				<div class="ppi-infobar" id="ppi-infobar">
					<span class="ppi-infobar-label">${__("Select a plan from the left")}</span>
				</div>

				<!-- Edit-mode options bar (shown when "View Only" is unchecked) -->
				<div class="ppi-editbar" id="ppi-editbar" style="display:none"></div>

				<!-- Legend bar -->
				<div class="ppi-stabs" id="ppi-stabs">
					<div class="ppi-stabs-spacer"></div>
					<span class="ppi-edit-hint" id="ppi-edit-hint">
						<span class="ppi-legend-dot ppi-legend-changed"></span>${__("Changed from DB")}
						&nbsp;&nbsp;
						<span class="ppi-legend-dot ppi-legend-actual"></span>${__("Actual (DB)")}
						&nbsp;&nbsp;
						<span id="ppi-autosave-status" style="font-size:11px;color:#6b7280;font-style:italic;"></span>
					</span>
				</div>

				<!-- FG Items Section -->
				<div class="ppi-section-hdr ppi-section-hdr--fg">
					<svg width="11" height="11" viewBox="0 0 12 12" fill="currentColor"><rect x="0" y="0" width="5" height="5" rx="1"/><rect x="7" y="0" width="5" height="5" rx="1"/><rect x="0" y="7" width="5" height="5" rx="1"/><rect x="7" y="7" width="5" height="5" rx="1"/></svg>
					${__("FG Items")}
					<span class="ppi-badge" id="ppi-badge-fg">—</span>
				</div>
				<div class="ppi-hot-wrap" id="ppi-hot-fg"></div>

				<!-- Sub Assembly Section -->
				<div class="ppi-section-hdr ppi-section-hdr--sfg">
					<svg width="11" height="11" viewBox="0 0 12 12" fill="currentColor"><path d="M6 0l6 3.5v5L6 12 0 8.5v-5z"/></svg>
					${__("Sub Assembly")}
					<span class="ppi-badge" id="ppi-badge-sfg">—</span>
				</div>
				<div class="ppi-hot-wrap" id="ppi-hot-sfg"></div>

				<!-- MR Items Section -->
				<div class="ppi-section-hdr ppi-section-hdr--mr">
					<svg width="11" height="11" viewBox="0 0 12 12" fill="currentColor"><rect x="0" y="0" width="12" height="3" rx="1"/><rect x="0" y="4.5" width="12" height="3" rx="1"/><rect x="0" y="9" width="12" height="3" rx="1"/></svg>
					${__("MR Items")}
					<span class="ppi-badge" id="ppi-badge-mr">—</span>
				</div>
				<div class="ppi-hot-wrap" id="ppi-hot-mr"></div>

			</div>
		</div>
	`);

	// Per-PP "View Only" checkbox (delegated — infobar re-renders on each switch)
	$root.on("change", "#ppi-excel-check", function () {
		if (!_current_pp) return;
		const old_val = _pp_use_excel[_current_pp] !== false;  // default true
		const checked = this.checked;
		_pp_use_excel[_current_pp] = checked;
		// Log per-PP setting (scoped to the actual pp_name, not importer doc)
		_pending_log_entries.push({
			pp_name:    _current_pp,
			table_name: "settings",
			row_name:   "_opts",
			field_name: "use_excel",
			old_value:  old_val ? "1" : "0",
			new_value:  checked ? "1" : "0",
		});
		clearTimeout(_log_flush_timer);
		_log_flush_timer = setTimeout(_flush_log, 1500);
		if (!checked) {
			frappe.show_alert({
				message: __("{0}: Edit mode enabled — modify dates and suppliers, then click Apply.", [_current_pp]),
				indicator: "blue",
			});
		}
		_render_editbar($root);
		// Toggle readonly state on all HOT grids immediately
		[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
	});

	// Edit-mode option controls (delegated — editbar re-renders on each PP switch)
	$root.on("change", "#ppi-shift-wise-check", function () {
		const old = _opt_shift_wise;
		_opt_shift_wise = this.checked;
		_log_setting("shift_wise", old ? "1" : "0", _opt_shift_wise ? "1" : "0");
		_render_editbar($root);
	});
	$root.on("change", "#ppi-backdated-check", function () {
		const old = _opt_backdated;
		_opt_backdated = this.checked;
		_log_setting("backdated", old ? "1" : "0", _opt_backdated ? "1" : "0");
	});
	$root.on("change", "#ppi-shift-type-input", function () {
		const old = _opt_shift_type;
		_opt_shift_type = this.value;
		_log_setting("shift_type", old, _opt_shift_type);
		_fetch_shift_details();
	});

	// Fetch all Shift Types + Manufacturing Settings default once at build time
	frappe.db.get_list("Shift Type", { fields: ["name"], limit: 0 })
		.then(rows => {
			_shift_types = rows.map(r => r.name).sort();
			_render_editbar($root);
		});
	frappe.db.get_single_value("Manufacturing Settings", "default_shift_type")
		.then(val => {
			if (val && !_opt_shift_type) {
				_opt_shift_type = val;
				_render_editbar($root);
				_fetch_shift_details();
			}
		});
}

// ─── Edit-mode options bar ─────────────────────────────────────────────────
function _render_editbar($root) {
	const useExcel = _current_pp ? (_pp_use_excel[_current_pp] !== false) : true;
	const $bar = $root.find("#ppi-editbar");
	if (useExcel || !_current_pp) {
		$bar.hide();
		return;
	}
	const shiftWrap = _opt_shift_wise ? `
		<div class="ppi-opt-shift-wrap">
			<span class="ppi-opt-shift-label">${__("Shift Type")}</span>
			<select id="ppi-shift-type-input" class="ppi-shift-select">
				<option value="">${__("— select —")}</option>
				${_shift_types.map(s =>
					`<option value="${frappe.utils.escape_html(s)}"${s === _opt_shift_type ? " selected" : ""}>${frappe.utils.escape_html(s)}</option>`
				).join("")}
			</select>
		</div>` : "";
	$bar.show().html(`
		<label class="ppi-opt-check-wrap">
			<input type="checkbox" id="ppi-shift-wise-check" ${_opt_shift_wise ? "checked" : ""}>
			<span class="ppi-opt-label">${__("Shift-wise Scheduling")}</span>
		</label>
		<label class="ppi-opt-check-wrap">
			<input type="checkbox" id="ppi-backdated-check" ${_opt_backdated ? "checked" : ""}>
			<span class="ppi-opt-label">${__("Allow Backdated")}</span>
		</label>
		${shiftWrap}
	`);
}

// ─── Load Production Plans directly from DB ────────────────────────────────
function _load_from_db(production_plans_json) {
	if (!_frm_ref) return;
	const $root = _frm_ref.fields_dict.importer_layout.$wrapper;

	let pp_names;
	try {
		pp_names = JSON.parse(production_plans_json || "[]");
	} catch(e) {
		pp_names = [];
	}

	if (!pp_names || !pp_names.length) {
		$root.find("#ppi-pp-tabs").html(
			`<div class="ppi-empty">${__("No Production Plans found.")}</div>`
		);
		return;
	}

	$root.find("#ppi-pp-tabs").html(
		`<div class="ppi-loading">${__("Loading Production Plans…")}</div>`
	);

	_pp_data = {};
	let fetched = 0;

	pp_names.forEach(pp_name => {
		frappe.call({
			method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.get_pp_importer_data",
			args: { production_plan_name: pp_name },
			callback(r) {
				if (r.message) {
					_pp_data[pp_name] = {
						po_items:  r.message.po_items  || [],
						sfg_items: r.message.sfg_items || [],
						mr_items:  r.message.mr_items  || [],
						docstatus: r.message.docstatus != null ? r.message.docstatus : 0,
					};
					// Capture DB baseline in _actual_* shadow fields (used for red-diff highlighting)
					_set_actual_fields(pp_name);
				}
				fetched++;
				if (fetched === pp_names.length) _after_load($root);
			},
			error() {
				fetched++;
				if (fetched === pp_names.length) _after_load($root);
			},
		});
	});
}

function _after_load($root) {
	_render_pp_tabs($root);
	_prefetch_suppliers();
	// Replay any unsaved HOT edits from the server change-log
	_replay_log_from_server($root);
}

// ─── Prefetch subcontracting suppliers for all item codes in loaded PPs ───
function _prefetch_suppliers() {
	const codes = new Set();
	Object.values(_pp_data).forEach(pp => {
		(pp.po_items  || []).forEach(r => r.item_code       && codes.add(r.item_code));
		(pp.sfg_items || []).forEach(r => r.production_item && codes.add(r.production_item));
		(pp.mr_items  || []).forEach(r => r.item_code       && codes.add(r.item_code));
	});
	if (!codes.size) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.get_item_suppliers",
		args: { item_codes: JSON.stringify([...codes]) },
		callback(r) {
			if (r.message) {
				_supplier_cache = r.message;
				// Re-render so supplier autocomplete activates in cells()
				[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
			}
		},
	});
}

// ─── Capture DB baseline into _actual_* shadow fields ──────────────────────
// Called right after _pp_data[pp_name] is populated from DB.
// _actual_* values show the "saved in DB" snapshot alongside any in-HOT edits (red = changed).
function _set_actual_fields(pp_name) {
	const pp = _pp_data[pp_name];
	if (!pp) return;

	(pp.po_items || []).forEach(row => {
		row._actual_planned_start_date       = row.planned_start_date       != null ? String(row.planned_start_date)       : "";
		row._actual_custom_planned_end_date  = row.custom_planned_end_date  != null ? String(row.custom_planned_end_date)  : "";
	});

	(pp.sfg_items || []).forEach(row => {
		row._actual_schedule_date            = row.schedule_date            != null ? String(row.schedule_date)            : "";
		row._actual_custom_schedule_end_date = row.custom_schedule_end_date != null ? String(row.custom_schedule_end_date) : "";
	});

	(pp.mr_items || []).forEach(row => {
		row._actual_custom_start_date = row.custom_start_date != null ? String(row.custom_start_date) : "";
		row._actual_schedule_date     = row.schedule_date     != null ? String(row.schedule_date)     : "";
	});
}

// ─── Left panel: PP tabs ───────────────────────────────────────────────────
function _render_pp_tabs($root) {
	const $wrap = $root.find("#ppi-pp-tabs").empty();
	Object.keys(_pp_data).forEach(pp_name => {
		const d = _pp_data[pp_name];
		const fg_n  = (d.po_items  || []).length;
		const sfg_n = (d.sfg_items || []).length;
		const mr_n  = (d.mr_items  || []).length;
		const status = _get_pp_status(pp_name);
		$(`
			<div class="ppi-pp-tab" data-pp="${pp_name}" data-status="${status}">
				<div class="ppi-pp-tab-name">${pp_name}</div>
				<div class="ppi-pp-tab-status ppi-pp-tab-status--${status}">
					<span class="ppi-pp-status-dot"></span>
					<span class="ppi-pp-status-text"></span>
				</div>
				<div class="ppi-pp-tab-meta">
					<span class="ppi-pp-chip ppi-pp-chip--fg">${fg_n} FG</span>
					<span class="ppi-pp-chip ppi-pp-chip--sfg">${sfg_n} SFG</span>
					<span class="ppi-pp-chip ppi-pp-chip--mr">${mr_n} MR</span>
				</div>
			</div>
		`).on("click", () => _switch_pp(pp_name)).appendTo($wrap);
	});
}

function _switch_pp(pp_name) {
	if (!_frm_ref) return;

	// Persist any in-progress edits before switching
	if (_current_pp) _flush_hot_to_data(_current_pp);

	_current_pp = pp_name;

	// Update active class
	_frm_ref.fields_dict.importer_layout.$wrapper
		.find(".ppi-pp-tab")
		.removeClass("active")
		.filter(`[data-pp="${pp_name}"]`)
		.addClass("active");

	// Update infobar + badges
	const data = _pp_data[pp_name];
	const $root = _frm_ref.fields_dict.importer_layout.$wrapper;

	// Default to false (edit mode) if not yet set for this PP
	if (_pp_use_excel[pp_name] === undefined) _pp_use_excel[pp_name] = false;
	const useExcel   = _pp_use_excel[pp_name];
	const docstatus  = data.docstatus || 0;
	const isDraft    = docstatus === 0;
	const isImported = !!(_pp_imported[pp_name] && _pp_imported[pp_name].ok);

	// Build docstatus chip
	const _DS_CHIP = {
		0: "",
		1: `<span class="ppi-ds-chip ppi-ds-chip--submitted">${__("Submitted")}</span>`,
		2: `<span class="ppi-ds-chip ppi-ds-chip--cancelled">${__("Cancelled")}</span>`,
	};

	$root.find("#ppi-infobar").html(`
		<span class="ppi-infobar-pp">${pp_name}</span>
		${_DS_CHIP[docstatus] || ""}
		<span class="ppi-infobar-sep">·</span>
		<span class="ppi-infobar-stat ppi-infobar-stat--fg">${(data.po_items||[]).length} FG</span>
		<span class="ppi-infobar-sep">·</span>
		<span class="ppi-infobar-stat ppi-infobar-stat--sfg">${(data.sfg_items||[]).length} SFG</span>
		<span class="ppi-infobar-sep">·</span>
		<span class="ppi-infobar-stat ppi-infobar-stat--mr">${(data.mr_items||[]).length} MR</span>
		<div class="ppi-infobar-spacer"></div>
		<label class="ppi-excel-check-wrap${isDraft && !isImported ? "" : " ppi-excel-check-wrap--disabled"}">
			<input type="checkbox" id="ppi-excel-check" ${useExcel ? "checked" : ""} ${isDraft && !isImported ? "" : "disabled"}>
			<span class="ppi-excel-check-label">${__("View Only")}</span>
		</label>
	`);
	$root.find("#ppi-badge-fg").text((data.po_items  || []).length);
	$root.find("#ppi-badge-sfg").text((data.sfg_items || []).length);
	$root.find("#ppi-badge-mr").text((data.mr_items  || []).length);
	_clear_links();
	_render_editbar($root);

	// Populate HOT instances
	if (_hot_fg) {
		_hot_fg.loadData(data.po_items || []);
	} else {
		_hot_fg = _make_hot("ppi-hot-fg", data.po_items || [], _FG_COLS,
			{ tableKey: "fg",  itemCodeField: "item_code",       supplierField: "custom_supplier", mfgTypeField: "custom_manufacturing_type" });
	}

	if (_hot_sfg) {
		_hot_sfg.loadData(data.sfg_items || []);
	} else {
		_hot_sfg = _make_hot("ppi-hot-sfg", data.sfg_items || [], _SFG_COLS,
			{ tableKey: "sfg", itemCodeField: "production_item", supplierField: "supplier",        mfgTypeField: "type_of_manufacturing" });
	}

	if (_hot_mr) {
		_hot_mr.loadData(data.mr_items || []);
	} else {
		_hot_mr = _make_hot("ppi-hot-mr", data.mr_items || [], _MR_COLS,
			{ tableKey: "mr",  itemCodeField: "item_code",       supplierField: "custom_supplier" });
	}

	// Overlay for submitted / cancelled docs
	_update_doc_state(docstatus);

	// Overlay for already-imported PPs (this session)
	_update_import_state(pp_name);

	// Re-render visible table to fix widths
	_re_render_active_hot();

	// Update apply button label for the newly active PP
	_update_apply_btn();
}

// ─── Re-render all HOT instances ──────────────────────────────────────────
// All three grids are always visible (vertical layout), so render all.
function _re_render_active_hot() {
	[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
}

// ─── Renderers ─────────────────────────────────────────────────────────────
// Strips the time portion so MR Date fields show only YYYY-MM-DD.
function _dateOnlyRenderer(hotInstance, TD, row, col, prop, value, cellProperties) {
	Handsontable.renderers.TextRenderer.apply(this, arguments);
	if (value && String(value).length > 10) {
		TD.innerHTML = String(value).substring(0, 10);
	}
}

// ─── Column definitions ────────────────────────────────────────────────────
// _actual_* columns are read-only DB snapshots shown right next to editable dates.
// Columns whose data key starts with "_actual_" are styled as ppi-actual-col.

const _MFG_TYPES = ["In House", "Subcontract"];

const _FG_COLS = [
	{ data: "name",                           title: "Row ID",        readOnly: true,  width: 120 },
	{ data: "item_code",                      title: "Item Code",     readOnly: true,  width: 150 },
	{ data: "sales_order",                    title: "Sales Order",   readOnly: true,  width: 140 },
	{ data: "planned_qty",                    title: "Qty",           readOnly: true,  width: 70,  type: "numeric" },
	{ data: "planned_start_date",             title: "Start Date",    readOnly: false, width: 165 },
	{ data: "_actual_planned_start_date",     title: "Saved Start",   readOnly: true,  width: 165 },
	{ data: "custom_planned_end_date",        title: "End Date",      readOnly: true,  width: 165 },
	{ data: "_actual_custom_planned_end_date",title: "Saved End",     readOnly: true,  width: 165 },
	{ data: "custom_manufacturing_type",      title: "Mfg Type",      readOnly: false, width: 110, type: "dropdown", source: _MFG_TYPES },
	{ data: "custom_supplier",                title: "Supplier",      readOnly: false, width: 160 },
];

const _SFG_COLS = [
	{ data: "name",                             title: "Row ID",        readOnly: true,  width: 120 },
	{ data: "production_item",                  title: "Item Code",     readOnly: true,  width: 120 },
	{ data: "item_name",                        title: "Item Name",     readOnly: true,  width: 170 },
	{ data: "bom_no",                           title: "BOM",           readOnly: true,  width: 140 },
	{ data: "qty",                              title: "Qty",           readOnly: true,  width: 70,  type: "numeric" },
	{ data: "schedule_date",                    title: "Start Date",    readOnly: false, width: 165 },
	{ data: "_actual_schedule_date",            title: "Saved Start",   readOnly: true,  width: 165 },
	{ data: "custom_schedule_end_date",         title: "End Date",      readOnly: false, width: 165 },
	{ data: "_actual_custom_schedule_end_date", title: "Saved End",     readOnly: true,  width: 165 },
	{ data: "type_of_manufacturing",            title: "Mfg Type",      readOnly: false, width: 110, type: "dropdown", source: _MFG_TYPES },
	{ data: "supplier",                         title: "Supplier",      readOnly: false, width: 160 },
];

const _MR_COLS = [
	{ data: "name",                      title: "Row ID",          readOnly: true,  width: 120 },
	{ data: "item_code",                 title: "Item Code",       readOnly: true,  width: 120 },
	{ data: "item_name",                 title: "Item Name",       readOnly: true,  width: 170 },
	{ data: "quantity",                  title: "Qty",             readOnly: true,  width: 70,  type: "numeric" },
	{ data: "custom_start_date",         title: "Start Date",   readOnly: false, width: 140, renderer: _dateOnlyRenderer },
	{ data: "_actual_custom_start_date", title: "Saved Start",  readOnly: true,  width: 140, renderer: _dateOnlyRenderer },
	{ data: "schedule_date",             title: "Required By",  readOnly: false, width: 140, renderer: _dateOnlyRenderer },
	{ data: "_actual_schedule_date",     title: "Saved Req By", readOnly: true,  width: 140, renderer: _dateOnlyRenderer },
	{ data: "custom_supplier",           title: "Supplier",        readOnly: false, width: 160 },
];

// ─── Cross-table row linkage ───────────────────────────────────────────────
// Flow: FG.name → SFG.production_plan_item → (via FG.sales_order) → MR.sales_order
// When any row is selected, all linked rows across the 3 tables are highlighted.

function _update_links(source, rowIdx) {
	_linked_rows = { fg: new Set(), sfg: new Set(), mr: new Set() };

	const fg_data  = _hot_fg  ? _hot_fg.getSourceData()  : [];
	const sfg_data = _hot_sfg ? _hot_sfg.getSourceData() : [];
	const mr_data  = _hot_mr  ? _hot_mr.getSourceData()  : [];

	let fg_name = null, fg_so = null;

	if (source === "fg") {
		const row = fg_data[rowIdx];
		if (!row) return;
		fg_name = row.name;
		fg_so   = row.sales_order;
		_linked_rows.fg.add(rowIdx);

	} else if (source === "sfg") {
		const row = sfg_data[rowIdx];
		if (!row) return;
		fg_name = row.production_plan_item;
		_linked_rows.sfg.add(rowIdx);
		// walk up to parent FG
		const fgIdx = fg_data.findIndex(r => r.name === fg_name);
		if (fgIdx >= 0) { fg_so = fg_data[fgIdx].sales_order; _linked_rows.fg.add(fgIdx); }

	} else if (source === "mr") {
		const row = mr_data[rowIdx];
		if (!row) return;
		fg_so = row.sales_order;
		_linked_rows.mr.add(rowIdx);
		// walk up to parent FG
		const fgIdx = fg_data.findIndex(r => r.sales_order === fg_so);
		if (fgIdx >= 0) { fg_name = fg_data[fgIdx].name; _linked_rows.fg.add(fgIdx); }
	}

	// All SFGs under the same FG
	if (fg_name) {
		sfg_data.forEach((r, i) => { if (r.production_plan_item === fg_name) _linked_rows.sfg.add(i); });
	}
	// All MRs under the same sales order
	if (fg_so) {
		mr_data.forEach((r, i) => { if (r.sales_order === fg_so) _linked_rows.mr.add(i); });
	}

	[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
}

function _clear_links() {
	if (!_linked_rows.fg.size && !_linked_rows.sfg.size && !_linked_rows.mr.size) return;
	_linked_rows = { fg: new Set(), sfg: new Set(), mr: new Set() };
	[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
}

// ─── Shift / validation helpers ───────────────────────────────────────────
function _time_to_mins(t) {
	if (!t) return null;
	const parts = String(t).split(":");
	return parseInt(parts[0] || 0, 10) * 60 + parseInt(parts[1] || 0, 10);
}

function _fetch_shift_details() {
	if (!_opt_shift_type) { _shift_details = null; return; }
	frappe.db.get_doc("Shift Type", _opt_shift_type).then(doc => { _shift_details = doc; });
}

// Returns error string if val violates backdate / shift-hour constraints, else null.
function _validate_hot_datetime(val) {
	if (!val) return null;
	const date_part = String(val).slice(0, 10);
	const time_part = String(val).length > 10 ? String(val).slice(11, 16) : null;

	if (!_opt_backdated) {
		const now   = new Date();
		const today = now.getFullYear() + "-" +
			String(now.getMonth() + 1).padStart(2, "0") + "-" +
			String(now.getDate()).padStart(2, "0");
		if (date_part < today) return __("Backdated dates are not allowed.");
		if (date_part === today && time_part) {
			const [h, m] = time_part.split(":").map(Number);
			if ((h * 60 + m) < (now.getHours() * 60 + now.getMinutes())) {
				return __("Past time not allowed.");
			}
		}
	}

	if (_opt_shift_wise && _shift_details && time_part) {
		const s      = _shift_details;
		const t_mins = parseInt(time_part.slice(0, 2), 10) * 60 + parseInt(time_part.slice(3, 5), 10);
		const sh_start = _time_to_mins(s.start_time);
		const sh_end   = _time_to_mins(s.end_time);
		const lu_start = _time_to_mins(s.custom_lunch_start_time);
		const lu_end   = _time_to_mins(s.custom_lunch_end_time);
		if (sh_start !== null && sh_end !== null && (t_mins < sh_start || t_mins > sh_end)) {
			return __("Time must be within shift hours ({0}\u2013{1}).")
				.replace("{0}", String(s.start_time).slice(0, 5))
				.replace("{1}", String(s.end_time).slice(0, 5));
		}
		if (lu_start !== null && lu_end !== null && t_mins >= lu_start && t_mins < lu_end) {
			return __("Lunch break ({0}\u2013{1}).")
				.replace("{0}", String(s.custom_lunch_start_time).slice(0, 5))
				.replace("{1}", String(s.custom_lunch_end_time).slice(0, 5));
		}
	}
	return null;
}

// Format a Date object → "YYYY-MM-DD HH:MM:SS" (local time)
function _fmt_dt(dt) {
	const p = n => String(n).padStart(2, "0");
	return `${dt.getFullYear()}-${p(dt.getMonth()+1)}-${p(dt.getDate())} ${p(dt.getHours())}:${p(dt.getMinutes())}:${p(dt.getSeconds())}`;
}

// ─── Date cascade functions ────────────────────────────────────────────────
// FG end date: recalculate custom_planned_end_date from start date (forward-schedule)
function _refresh_fg_end_date(fgRowIdx, new_start) {
	const row = _hot_fg && _hot_fg.getSourceData()[fgRowIdx];
	if (!row || !new_start) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_fg_dates.recalculate_fg_end_date",
		args: {
			planned_start_date: new_start,
			bom_no:             row.bom_no                    || "",
			planned_qty:        row.planned_qty               || 0,
			manufacturing_type: row.custom_manufacturing_type || "",
			item_code:          row.item_code                 || "",
			supplier:           row.custom_supplier           || "",
		},
		callback(r) {
			const end_val = r.message && r.message.custom_planned_end_date;
			if (end_val) {
				_hot_fg.setDataAtRowProp(fgRowIdx, "custom_planned_end_date", end_val, "cascade");
			}
		},
	});
}

// FG start date changed → update FG end date + recalculate whole SFG chain → then MR
function _cascade_fg_start_to_sfg_mr(fgRowIdx, new_start) {
	const row = _hot_fg && _hot_fg.getSourceData()[fgRowIdx];
	if (!row || !_current_pp) return;
	// Update FG end date in parallel with SFG chain recalc
	_refresh_fg_end_date(fgRowIdx, new_start);
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_sfg_dates.recalculate_sfg_chain_dates",
		args: {
			production_plan_name:   _current_pp,
			po_item_name:           row.name,
			new_planned_start_date: new_start,
		},
		callback(r) {
			const results  = r.message || {};
			const sfg_data = _hot_sfg && _hot_sfg.getSourceData();
			if (sfg_data) {
				sfg_data.forEach((sfgRow, i) => {
					const d = results[sfgRow.name];
					if (d) {
						_hot_sfg.setDataAtRowProp(i, "schedule_date",            d.schedule_date            || "", "cascade");
						_hot_sfg.setDataAtRowProp(i, "custom_schedule_end_date", d.custom_schedule_end_date || "", "cascade");
					}
				});
			}
			_cascade_sfg_to_mr(row.name);
		},
	});
}

// SFG start or end date changed → recalculate the other side → then MR
function _cascade_sfg_date_changed(sfgRowIdx, prop, newVal) {
	const sfg_data = _hot_sfg && _hot_sfg.getSourceData();
	const row      = sfg_data && sfg_data[sfgRowIdx];
	if (!row || !_current_pp) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_sfg_dates.recalculate_sfg_row_dates",
		args: {
			production_plan_name: _current_pp,
			sfg_row_name:         row.name,
			changed_field:        prop,
			new_value:            newVal,
			override_mfg_type:    row.type_of_manufacturing || "",
			override_supplier:    row.supplier              || "",
		},
		callback(r) {
			const res = r.message || {};
			if (!res.schedule_date) return;
			if (res.clamped) {
				frappe.show_alert({ message: __("Date clamped — moved to today."), indicator: "orange" });
			}
			const other_prop = prop === "schedule_date" ? "custom_schedule_end_date" : "schedule_date";
			const other_val  = prop === "schedule_date" ? res.custom_schedule_end_date : res.schedule_date;
			_hot_sfg.setDataAtRowProp(sfgRowIdx, other_prop, other_val || "", "cascade");
			// Cascade start down to child SFGs (tight-chain, in-memory)
			_cascade_sfg_downward_hot(sfgRowIdx, res.schedule_date);
			// Cascade end up to ancestor SFGs + FG; MR refresh happens inside upward callback
			_cascade_sfg_upward_hot(sfgRowIdx, res.custom_schedule_end_date, row.production_plan_item);
		},
	});
}

// SFG dates updated → recalculate MR dates for the same FG chain
function _cascade_sfg_to_mr(po_item_name) {
	if (!_current_pp || !_hot_sfg || !_hot_mr) return;
	const sfg_dates_data = _hot_sfg.getSourceData()
		.filter(r => r.production_plan_item === po_item_name && r.schedule_date)
		.map(r => ({
			name:                     r.name,
			schedule_date:            r.schedule_date,
			custom_schedule_end_date: r.custom_schedule_end_date || "",
		}));
	if (!sfg_dates_data.length) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.recalculate_mr_dates_from_sfg",
		args: {
			production_plan_name: _current_pp,
			sfg_dates_data:       JSON.stringify(sfg_dates_data),
			po_item_name:         po_item_name,
		},
		callback(r) {
			const results = r.message || {};
			_hot_mr.getSourceData().forEach((mrRow, i) => {
				const d = results[mrRow.name];
				if (d) {
					if (d.custom_start_date) _hot_mr.setDataAtRowProp(i, "custom_start_date", String(d.custom_start_date).slice(0, 10), "cascade");
					if (d.schedule_date)     _hot_mr.setDataAtRowProp(i, "schedule_date",     String(d.schedule_date).slice(0, 10),     "cascade");
				}
			});
		},
	});
}

// SFG start changed → cascade tight-chain down to children (pure in-memory, no API)
// child.new_end = parent.new_start; duration preserved → child.new_start = child.new_end - dur
function _cascade_sfg_downward_hot(sfgRowIdx, new_start_str) {
	if (!_hot_sfg || !new_start_str) return;
	const sfg_data    = _hot_sfg.getSourceData();
	const changed_row = sfg_data[sfgRowIdx];
	if (!changed_row) return;

	const chain_id = changed_row.production_plan_item;

	// production_item → [child rows] (within same FG chain)
	const parent_to_children = {};
	sfg_data.forEach(r => {
		if (r.production_plan_item !== chain_id || !r.parent_item_code) return;
		if (!parent_to_children[r.parent_item_code]) parent_to_children[r.parent_item_code] = [];
		parent_to_children[r.parent_item_code].push(r);
	});

	// BFS from changed row downward
	const queue = [{ pi: changed_row.production_item, ns: new_start_str }];
	while (queue.length) {
		const { pi, ns: parent_new_start } = queue.shift();
		(parent_to_children[pi] || []).forEach(child => {
			const cs = child.schedule_date;
			const ce = child.custom_schedule_end_date;
			if (!cs || !ce) return;

			const start_ms = new Date(cs.replace(" ", "T")).getTime();
			const end_ms   = new Date(ce.replace(" ", "T")).getTime();
			const dur_ms   = end_ms - start_ms;

			const new_end_dt   = new Date(parent_new_start.replace(" ", "T"));
			const new_start_dt = new Date(new_end_dt.getTime() - dur_ms);
			const ns = _fmt_dt(new_start_dt);
			const ne = _fmt_dt(new_end_dt);

			const idx = sfg_data.findIndex(r => r.name === child.name);
			if (idx >= 0) {
				_hot_sfg.setDataAtRowProp(idx, "schedule_date",            ns, "cascade");
				_hot_sfg.setDataAtRowProp(idx, "custom_schedule_end_date", ne, "cascade");
			}
			queue.push({ pi: child.production_item, ns });
		});
	}
}

// SFG end date changed → cascade upward to ancestor SFGs + FG → then refresh MR
function _cascade_sfg_upward_hot(sfgRowIdx, new_end_str, po_item_name) {
	const sfg_data = _hot_sfg && _hot_sfg.getSourceData();
	const row      = sfg_data && sfg_data[sfgRowIdx];
	if (!row || !_current_pp) return;

	// Pass current HOT FG planned_start_date so the server compares push_end against the
	// in-memory value, not the (potentially stale) DB value — prevents FG reverting silently.
	const fg_data           = _hot_fg && _hot_fg.getSourceData();
	const fg_row            = fg_data && fg_data.find(r => r.name === po_item_name);
	const fg_start_override = (fg_row && fg_row.planned_start_date) || "";

	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_sfg_dates.recalculate_sfg_chain_upward",
		args: {
			production_plan_name: _current_pp,
			changed_sfg_name:     row.name,
			new_end_date:         new_end_str,
			fg_start_override:    fg_start_override,
		},
		callback(r) {
			const sfg_updates = (r.message && r.message.sfg_updates) || {};
			const fg_update   = (r.message && r.message.fg_update)   || {};
			const sfg_count   = Object.keys(sfg_updates).length;
			const fg_count    = Object.keys(fg_update).length;

			sfg_data.forEach((sfgRow, i) => {
				const d = sfg_updates[sfgRow.name];
				if (d) {
					_hot_sfg.setDataAtRowProp(i, "schedule_date",            d.schedule_date            || "", "cascade");
					_hot_sfg.setDataAtRowProp(i, "custom_schedule_end_date", d.custom_schedule_end_date || "", "cascade");
				}
			});

			const fg_data = _hot_fg && _hot_fg.getSourceData();
			if (fg_data) {
				fg_data.forEach((fgRow, i) => {
					const d = fg_update[fgRow.name];
					if (d) {
						_hot_fg.setDataAtRowProp(i, "planned_start_date",      d.planned_start_date      || "", "cascade");
						_hot_fg.setDataAtRowProp(i, "custom_planned_end_date", d.custom_planned_end_date || "", "cascade");
					}
				});
			}

			if (sfg_count > 0 || fg_count > 0) {
				frappe.show_alert({
					message: __(`${sfg_count} upstream SFG and ${fg_count} FG row(s) rescheduled.`),
					indicator: "blue",
				});
			}
			// Refresh MR after all upstream changes settle
			_cascade_sfg_to_mr(po_item_name);
		},
	});
}

// MR schedule_date changed → propagate upward to SFG + FG
function _cascade_mr_to_sfg_fg(mrRowIdx) {
	const mr_data = _hot_mr && _hot_mr.getSourceData();
	const row     = mr_data && mr_data[mrRowIdx];
	if (!row || !_current_pp) return;

	// {item_code: max_schedule_date} across all MR rows (same as dialog logic)
	const mr_schedule_dates = {};
	mr_data.forEach(r => {
		const sd = r.schedule_date || "";
		if (!sd) return;
		if (!mr_schedule_dates[r.item_code] || sd > mr_schedule_dates[r.item_code])
			mr_schedule_dates[r.item_code] = sd;
	});

	const sfg_override = (_hot_sfg ? _hot_sfg.getSourceData() : []).map(r => ({
		name:                     r.name,
		schedule_date:            r.schedule_date            || "",
		custom_schedule_end_date: r.custom_schedule_end_date || "",
	}));
	const fg_override = (_hot_fg ? _hot_fg.getSourceData() : []).map(r => ({
		name:                   r.name,
		planned_start_date:     r.planned_start_date     || "",
		custom_planned_end_date: r.custom_planned_end_date || "",
	}));

	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.propagate_mr_schedule_to_sfg_fg",
		args: {
			production_plan_name: _current_pp,
			mr_schedule_dates:    JSON.stringify(mr_schedule_dates),
			sfg_dates_override:   JSON.stringify(sfg_override),
			fg_dates_override:    JSON.stringify(fg_override),
			mr_row_name_filter:   row.name,
		},
		callback(r) {
			const sfg_updates = (r.message && r.message.sfg_updates) || {};
			const fg_updates  = (r.message && r.message.fg_updates)  || {};
			const sfg_count   = Object.keys(sfg_updates).length;
			const fg_count    = Object.keys(fg_updates).length;

			const sfg_data = _hot_sfg && _hot_sfg.getSourceData();
			if (sfg_data) {
				sfg_data.forEach((sfgRow, i) => {
					const d = sfg_updates[sfgRow.name];
					if (d) {
						_hot_sfg.setDataAtRowProp(i, "schedule_date",            d.schedule_date            || "", "cascade");
						_hot_sfg.setDataAtRowProp(i, "custom_schedule_end_date", d.custom_schedule_end_date || "", "cascade");
					}
				});
			}

			const fg_data = _hot_fg && _hot_fg.getSourceData();
			if (fg_data) {
				fg_data.forEach((fgRow, i) => {
					const d = fg_updates[fgRow.name];
					if (d) {
						_hot_fg.setDataAtRowProp(i, "planned_start_date",       d.planned_start_date       || "", "cascade");
						_hot_fg.setDataAtRowProp(i, "custom_planned_end_date",  d.custom_planned_end_date  || "", "cascade");
					}
				});
			}

			if (sfg_count > 0 || fg_count > 0) {
				frappe.show_alert({
					message: __(`MR change cascaded — ${sfg_count} SFG and ${fg_count} FG row(s) updated.`),
					indicator: "blue",
				});
			}
		},
	});
}

// MR custom_start_date or supplier changed → recalculate schedule_date via API → cascade upward
// new_start: pass the new date string when start changed, null to use current row value
// new_supplier: pass the new supplier when supplier changed, null to use current row value
function _recalc_mr_schedule_from_start(mrRowIdx, new_start, new_supplier) {
	const mr_data = _hot_mr && _hot_mr.getSourceData();
	const row     = mr_data && mr_data[mrRowIdx];
	if (!row || !_current_pp) return;
	const start_date = new_start != null ? new_start : (row.custom_start_date || "");
	if (!start_date) return;
	const supplier = new_supplier != null ? new_supplier : (row.custom_supplier || "");
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.recalculate_mr_schedule_date",
		args: {
			production_plan_name: _current_pp,
			mr_row_name:          row.name,
			new_start_date:       start_date,
			supplier_override:    supplier,
		},
		callback(r) {
			const res = r.message || {};
			if (res.schedule_date) {
				_hot_mr.setDataAtRowProp(mrRowIdx, "schedule_date", res.schedule_date.slice(0, 10), "cascade");
			}
			_cascade_mr_to_sfg_fg(mrRowIdx);
		},
	});
}

// ─── Handsontable factory ──────────────────────────────────────────────────
// opts.itemCodeField : row field to look up in _supplier_cache (e.g. "item_code", "production_item")
// opts.supplierField : column data key for supplier (e.g. "custom_supplier", "supplier")
// opts.tableKey      : "fg" | "sfg" | "mr" — used for cross-table link highlighting
function _make_hot(container_id, data, columns, opts) {
	const el = document.getElementById(container_id);
	if (!el) return null;

	const itemCodeField = (opts && opts.itemCodeField) || "item_code";
	const supplierField = (opts && opts.supplierField) || "custom_supplier";

	let hot;
	hot = new Handsontable(el, {
		data,
		columns,
		colHeaders: columns.map(c => c.title),
		rowHeaders:            true,
		licenseKey:            "non-commercial-and-evaluation",
		stretchH:              "last",
		height:                "auto",
		contextMenu:           false,
		manualColumnResize:    true,
		wordWrap:              false,
		outsideClickDeselects: false,

		// Color-code header TH elements: editable columns get a white underline,
		// Saved (DB) columns get a green underline.
		afterGetColHeader(col, TH) {
			const c = columns[col];
			if (!c) return;
			TH.classList.remove("ppi-th--editable", "ppi-th--saved");
			if (c.data && c.data.startsWith("_actual_")) {
				TH.classList.add("ppi-th--saved");
			} else if (c.readOnly === false) {
				TH.classList.add("ppi-th--editable");
			}
		},

		cells(row, col) {
			const colDef    = columns[col];
			const cls       = [];
			const ppDoc     = _current_pp && _pp_data[_current_pp];
			const docstatus = ppDoc ? (ppDoc.docstatus || 0) : 0;
			// viewOnly true (checked) = readonly grids; false (unchecked) = edit mode
			const useExcel     = _current_pp ? (_pp_use_excel[_current_pp] === true) : false;
			// Lock cells after a successful import (user must clear overlay / re-edit to re-apply)
			const isImported   = _current_pp && _pp_imported[_current_pp] && _pp_imported[_current_pp].ok;

			const isActual          = colDef && colDef.data && colDef.data.startsWith("_actual_");
			const isInherentlyEdit  = colDef && !colDef.readOnly && !isActual;
			// effective readonly: submitted/cancelled OR imported OR column not editable OR view-only mode
			const effectiveRO       = docstatus !== 0 || isImported || !isInherentlyEdit || useExcel;

			if (effectiveRO)    cls.push("ppi-readonly-cell");
			if (isActual)       cls.push("ppi-actual-col");
			if (row % 2 === 1)  cls.push("ppi-row-alt");

			// Cross-table linkage highlight
			const tableKey = opts && opts.tableKey;
			if (tableKey && _linked_rows[tableKey] && _linked_rows[tableKey].has(row)) {
				cls.push("ppi-linked-row");
			}

			// Red highlight when the cell value differs from its DB-saved counterpart.
			// Shown in both view-only and edit-mode — useful feedback either way.
			if (isInherentlyEdit && hot) {
				const rowData = hot.getSourceDataAtRow(row);
				if (rowData) {
					const actualKey = "_actual_" + colDef.data;
					const actualVal = rowData[actualKey];
					const curVal    = rowData[colDef.data];
					if (actualVal !== undefined &&
						String(curVal  || "").trim() !== String(actualVal || "").trim()) {
						cls.push("ppi-changed-cell");
					}
				}
			}

			const cellProps = {
				readOnly:  effectiveRO,
				className: cls.join(" ") || undefined,
			};

			// Supplier — only editable when manufacturing type is "Subcontract"
			if (colDef && colDef.data === supplierField) {
				const mfgTypeField  = opts && opts.mfgTypeField;
				let supplierEditable = !effectiveRO;

				if (supplierEditable && mfgTypeField && hot) {
					const rowData = hot.getSourceDataAtRow(row);
					const mfgType = rowData && rowData[mfgTypeField];
					if (mfgType !== "Subcontract") {
						supplierEditable = false;
					}
				}

				if (!supplierEditable) {
					cellProps.readOnly = true;
					if (!cls.includes("ppi-readonly-cell")) cls.push("ppi-readonly-cell");
					cellProps.className = cls.join(" ") || undefined;
				} else if (hot) {
					const rowData  = hot.getSourceDataAtRow(row);
					const itemCode = rowData && rowData[itemCodeField];
					const sups     = (itemCode && _supplier_cache[itemCode]) || [];
					if (sups.length) {
						cellProps.type   = "autocomplete";
						cellProps.source = sups;
						cellProps.strict = false;
					}
				}
			}

			return cellProps;
		},

		// Validate dates + cascade; also re-render when mfg type changes.
		afterChange(changes, source) {
			if (!changes) return;
			const mfgTypeField = opts && opts.mfgTypeField;
			const tableKey     = opts && opts.tableKey;

			// Log ALL non-loadData changes (user edits AND cascade results) to the server.
			if (source !== "loadData") {
				changes.forEach(([row, prop, oldVal, newVal]) => {
					const rowData = hot.getSourceDataAtRow(row);
					_queue_log(tableKey, rowData && rowData.name, prop, oldVal, newVal);
				});
			}

			// Skip cascade logic for non-user sources
			if (source === "cascade" || source === "revert" || source === "loadData") return;

			// Track pending edits + update sidebar badge/button
			if (_current_pp) {
				_pp_has_edits[_current_pp] = true;
				// Clear the "Imported" overlay so cells become editable again (status → "partial")
				if (_pp_imported[_current_pp] && _pp_imported[_current_pp].ok) {
					delete _pp_imported[_current_pp];
					_update_import_state(_current_pp);
				}
				_refresh_pp_tab_status(_current_pp);
				_update_apply_btn();
			}
			const DATE_FIELDS  = {
				fg:  ["planned_start_date"],
				sfg: ["schedule_date", "custom_schedule_end_date"],
				mr:  ["custom_start_date", "schedule_date"],
			};
			const dateFields   = (tableKey && DATE_FIELDS[tableKey]) || [];

			changes.forEach(([row, prop, oldVal, newVal]) => {
				if (mfgTypeField && prop === mfgTypeField) {
					hot.render();
					// FG mfg type change also affects end date (In House vs Subcontract logic)
					if (tableKey === "fg") {
						const rowData = hot.getSourceDataAtRow(row);
						if (rowData && rowData.planned_start_date) {
							_refresh_fg_end_date(row, rowData.planned_start_date);
						}
					}
					return;
				}

				// MR supplier change → recalculate schedule_date with new lead time → cascade upward
				if (tableKey === "mr" && prop === "custom_supplier") {
					if (newVal !== oldVal) _recalc_mr_schedule_from_start(row, null, newVal);
					return;
				}

				if (!dateFields.includes(prop) || !newVal || newVal === oldVal) return;

				const err = _validate_hot_datetime(newVal);
				if (err) {
					setTimeout(() => {
						hot.setDataAtRowProp(row, prop, oldVal, "revert");
						frappe.show_alert({ message: err, indicator: "orange" });
					}, 0);
					return;
				}

				if (tableKey === "fg" && prop === "planned_start_date") {
					_cascade_fg_start_to_sfg_mr(row, newVal);
				} else if (tableKey === "sfg") {
					_cascade_sfg_date_changed(row, prop, newVal);
				} else if (tableKey === "mr" && prop === "schedule_date") {
					_cascade_mr_to_sfg_fg(row);
				} else if (tableKey === "mr" && prop === "custom_start_date") {
					_recalc_mr_schedule_from_start(row, newVal, null);
				}
			});
		},

		// Cross-table linkage: highlight linked rows in all 3 tables on row select/deselect
		afterSelectionEnd(row) {
			if (row >= 0) _update_links((opts && opts.tableKey) || "fg", row);
		},
		afterDeselect() {
			_clear_links();
		},
	});
	return hot;
}

// ─── Submitted / Cancelled overlay ────────────────────────────────────────
const _DOC_STATE = { 0: null, 1: "Submitted", 2: "Cancelled" };

function _update_doc_state(docstatus) {
	const label = _DOC_STATE[docstatus];

	["fg", "sfg", "mr"].forEach(sec => {
		const wrap = document.getElementById(`ppi-hot-${sec}`);
		if (!wrap) return;

		// Remove any existing overlay
		const old = wrap.querySelector(".ppi-doc-overlay");
		if (old) old.remove();

		if (label) {
			const ov = document.createElement("div");
			ov.className = "ppi-doc-overlay ppi-doc-overlay--" + (docstatus === 2 ? "cancelled" : "submitted");
			ov.innerHTML = `<span class="ppi-doc-overlay-badge">${__(label)}</span>`;
			wrap.appendChild(ov);
		}
	});

	// Also re-render HOTs so cells() reflects docstatus
	[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
}

// ─── Flush HOT edits back to _pp_data ────────────────────────────────────
function _flush_hot_to_data(pp_name) {
	if (!pp_name || !_pp_data[pp_name]) return;
	if (_hot_fg)  _pp_data[pp_name].po_items  = _hot_fg.getSourceData().map(r => ({ ...r }));
	if (_hot_sfg) _pp_data[pp_name].sfg_items = _hot_sfg.getSourceData().map(r => ({ ...r }));
	if (_hot_mr)  _pp_data[pp_name].mr_items  = _hot_mr.getSourceData().map(r => ({ ...r }));
}

// ─── Server-side change log ────────────────────────────────────────────────
// Every HOT edit (user or cascade) is buffered and flushed to PP Importer Log
// (a standalone Frappe DocType) with a 1.5 s debounce. On page reload the log
// is replayed so unsaved edits survive navigation, browser-data clearing, etc.

// Queue one HOT change for server-side logging.
// Called from afterChange for ALL sources except "loadData".
function _queue_log(table_name, row_name, field_name, old_val, new_val) {
	if (!_frm_ref || !_current_pp || !row_name) return;
	// Skip internal shadow / metadata fields — only log editable data fields
	if (String(field_name).startsWith("_")) return;
	_pending_log_entries.push({
		pp_name:    _current_pp,
		table_name: table_name,
		row_name:   row_name,
		field_name: field_name,
		old_value:  old_val != null ? String(old_val) : "",
		new_value:  new_val != null ? String(new_val) : "",
	});
	clearTimeout(_log_flush_timer);
	_log_flush_timer = setTimeout(_flush_log, 1500);
}

// Queue a global edit-mode settings change (shift_wise, backdated, shift_type).
// Scoped to the importer doc name so different importer docs have independent settings.
function _log_setting(field_name, old_val, new_val) {
	if (!_frm_ref) return;
	_pending_log_entries.push({
		pp_name:    _frm_ref.doc.name,  // importer doc name as scope key
		table_name: "settings",
		row_name:   "_opts",
		field_name: field_name,
		old_value:  old_val != null ? String(old_val) : "",
		new_value:  new_val != null ? String(new_val) : "",
	});
	clearTimeout(_log_flush_timer);
	_log_flush_timer = setTimeout(_flush_log, 1500);
}

// Build the full list of pp_names used for log queries:
// actual PP names + importer doc name (scope for global settings).
function _log_pp_names() {
	const names = Object.keys(_pp_data);
	if (_frm_ref) names.push(_frm_ref.doc.name);
	return names;
}

// Send all buffered entries to the server in one call.
// Shows a brief "auto-saved" indicator on success.
function _flush_log() {
	if (!_pending_log_entries.length || !_frm_ref) return;
	const entries = _pending_log_entries.splice(0);
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.batch_log_hot_changes",
		args: {
			importer_doc: _frm_ref.doc.name,
			changes:      JSON.stringify(entries),
		},
		callback() {
			// Real-time indicator: update the autosave status element
			const now = new Date();
			const hms = String(now.getHours()).padStart(2,"0") + ":"
				+ String(now.getMinutes()).padStart(2,"0") + ":"
				+ String(now.getSeconds()).padStart(2,"0");
			const el = document.getElementById("ppi-autosave-status");
			if (el) el.textContent = __("Logged at {0}", [hms]);
		},
	});
}

// Fetch HOT change log + previous import status in parallel, then replay onto
// freshly-loaded _pp_data. Both calls complete before _switch_pp is called,
// so the Imported overlay and readonly state are in place from the first render.
function _replay_log_from_server() {
	if (!_frm_ref) return;

	let _pending        = 2;           // decremented by each parallel call
	let _log_entries    = [];
	let _import_statuses = {};

	const _both_done = () => {
		const importer_scope     = _frm_ref.doc.name;
		const pp_names_with_edits = new Set();

		// ── 1. Apply import statuses FIRST so cells() gets correct readonly state ──
		Object.entries(_import_statuses).forEach(([pp, info]) => {
			if (info.status === "Success") {
				_pp_imported[pp] = { ok: true };
			} else if (info.status === "Error") {
				_pp_imported[pp] = { ok: false, error: info.error_message || "" };
			}
		});

		// ── 2. Replay HOT change log entries (settings + row edits) ──
		let restored          = false;
		let settings_restored = false;

		_log_entries.forEach(entry => {
			if (entry.table_name === "settings") {
				const v = entry.new_value != null ? String(entry.new_value) : "";
				if (entry.pp_name === importer_scope) {
					if      (entry.field_name === "shift_wise") { _opt_shift_wise = v === "1"; settings_restored = true; }
					else if (entry.field_name === "backdated")  { _opt_backdated  = v === "1"; settings_restored = true; }
					else if (entry.field_name === "shift_type") { _opt_shift_type = v;          settings_restored = true; }
				} else {
					if (entry.field_name === "use_excel" && _pp_data[entry.pp_name] !== undefined) {
						_pp_use_excel[entry.pp_name] = v === "1";
						settings_restored = true;
					}
				}
				return;
			}

			// HOT row edits
			const data = _pp_data[entry.pp_name];
			if (!data) return;
			const items =
				entry.table_name === "fg"  ? data.po_items  :
				entry.table_name === "sfg" ? data.sfg_items :
				                             data.mr_items;
			if (!items) return;
			const row = items.find(r => r.name === entry.row_name);
			if (!row) return;
			row[entry.field_name] = entry.new_value != null ? String(entry.new_value) : "";
			restored = true;
			pp_names_with_edits.add(entry.pp_name);
		});

		// ── 3. If a PP has new unsaved edits written AFTER its last import,
		//       clear the imported state — user is re-editing, not done yet ──
		pp_names_with_edits.forEach(pp => {
			if (_pp_imported[pp]) delete _pp_imported[pp];
			_pp_has_edits[pp] = true; // mark as pending
		});

		if (settings_restored && _opt_shift_type) _fetch_shift_details();

		if (restored || settings_restored) {
			frappe.show_alert({
				message: __("Unsaved edits restored from change log. Click \"Apply to Production Plan\" to save them."),
				indicator: "yellow",
			});
		}

		// ── 4. Show the first PP with all state already set ──
		const first = Object.keys(_pp_data)[0];
		if (first) {
			_switch_pp(first);       // _update_import_state is called inside _switch_pp
			_refresh_all_pp_tab_statuses(); // sync sidebar badges with restored state
			if (restored || settings_restored) {
				const _now = new Date();
				const _hms = String(_now.getHours()).padStart(2,"0") + ":" +
					String(_now.getMinutes()).padStart(2,"0") + ":" +
					String(_now.getSeconds()).padStart(2,"0");
				const _el = document.getElementById("ppi-autosave-status");
				if (_el) _el.textContent = __("Restored at {0}", [_hms]);
			}
		}
	};

	// ── Parallel call A: HOT change log ─────────────────────────────────────
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.get_hot_log",
		args: { pp_names: JSON.stringify(_log_pp_names()) },
		callback(r) { _log_entries = r.message || []; if (--_pending === 0) _both_done(); },
		error()    {                                    if (--_pending === 0) _both_done(); },
	});

	// ── Parallel call B: previous import results (PP Import Log) ────────────
	const _actual_pp_names = Object.keys(_pp_data);
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.get_import_log_status",
		args: { importer_doc: _frm_ref.doc.name, pp_names: JSON.stringify(_actual_pp_names) },
		callback(r) { _import_statuses = r.message || {}; if (--_pending === 0) _both_done(); },
		error()    {                                        if (--_pending === 0) _both_done(); },
	});
}

// Delete all log entries for this session's PP names (called after successful Apply).
function _clear_log() {
	clearTimeout(_log_flush_timer);
	_pending_log_entries = [];
	if (!_frm_ref) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.clear_hot_log",
		args: { pp_names: JSON.stringify(_log_pp_names()) },
	});
}

// ─── Apply to Production Plans ────────────────────────────────────────────
// Applies the CURRENT PP only (not all). Logs result to PP Import Log.
// Button label updates based on the resulting status.
function _apply_to_pp() {
	if (!_current_pp || !_pp_data[_current_pp]) {
		frappe.show_alert({ message: __("No Production Plan loaded."), indicator: "orange" });
		return;
	}

	// Flush any in-progress HOT edits into _pp_data
	_flush_hot_to_data(_current_pp);

	const pp_name = _current_pp;
	const data    = _pp_data[pp_name];

	const $btn = _apply_btn;
	if ($btn) $btn.prop("disabled", true).text(__("Saving…"));

	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.apply_pp_import",
		args: {
			importer_doc:         _frm_ref.doc.name,
			production_plan_name: pp_name,
			po_items_data: JSON.stringify(
				(data.po_items || []).map(r => ({
					name:                      r.name,
					planned_start_date:        r.planned_start_date        || null,
					custom_planned_end_date:   r.custom_planned_end_date   || null,
					custom_manufacturing_type: r.custom_manufacturing_type || null,
					custom_supplier:           r.custom_supplier           || null,
				}))
			),
			sfg_data: JSON.stringify(
				(data.sfg_items || []).map(r => ({
					name:                     r.name,
					schedule_date:            r.schedule_date            || null,
					custom_schedule_end_date: r.custom_schedule_end_date || null,
					type_of_manufacturing:    r.type_of_manufacturing    || null,
					supplier:                 r.supplier                 || null,
				}))
			),
			mr_data: JSON.stringify(
				(data.mr_items || []).map(r => ({
					name:              r.name,
					custom_start_date: r.custom_start_date || null,
					schedule_date:     r.schedule_date     || null,
					custom_supplier:   r.custom_supplier   || null,
				}))
			),
		},
		callback(r) {
			const res = r.message || {};
			if ($btn) $btn.prop("disabled", false);

			if (res.status === "ok") {
				_pp_imported[pp_name] = { ok: true };
				delete _pp_has_edits[pp_name];
				_clear_pp_log(pp_name);
				frappe.show_alert({ message: __("{0} applied successfully.", [pp_name]), indicator: "green" });
			} else {
				_pp_imported[pp_name] = { ok: false, error: res.message || __("Unknown error") };
				frappe.show_alert({ message: __("Apply failed: {0}", [res.message || ""]), indicator: "red" });
			}
			_update_import_state(pp_name);
			_refresh_pp_tab_status(pp_name);
			_update_apply_btn();
			_update_importer_status(); // sync importer doc status field
		},
		error() {
			if ($btn) $btn.prop("disabled", false);
			_pp_imported[pp_name] = { ok: false, error: __("Network or server error") };
			_update_import_state(pp_name);
			_refresh_pp_tab_status(pp_name);
			_update_apply_btn();
			_update_importer_status(); // sync importer doc status field
		},
	});
}

// ─── Importer doc status ──────────────────────────────────────────────────
// Queries PP Import Log to determine overall status across all PPs in the file
// and persists it to the Production Plan Importer doc (status field).
//   Fully Imported    → every PP has a latest "Success" entry
//   Partially Imported → at least one success, at least one not
//   Pending Import    → no successes yet
function _update_importer_status() {
	if (!_frm_ref) return;
	const all_pps = Object.keys(_pp_data);
	if (!all_pps.length) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.update_importer_status",
		args: { importer_doc: _frm_ref.doc.name, all_pp_names: JSON.stringify(all_pps) },
		callback(r) {
			const new_status = r.message && r.message.importer_status;
			if (new_status && _frm_ref) {
				_frm_ref.doc.status = new_status;
				_frm_ref.refresh_field("status");
			}
		},
	});
}

// ─── Import state overlay ──────────────────────────────────────────────────
// Shows "Imported" (green) or "Import Failed" (red) overlay after Apply.
// Makes cells read-only after a successful import (re-import is possible after
// editing again — _pp_imported entry is cleared on next HOT edit).
function _update_import_state(pp_name) {
	const imp = _pp_imported[pp_name];

	["fg", "sfg", "mr"].forEach(sec => {
		const wrap = document.getElementById(`ppi-hot-${sec}`);
		if (!wrap) return;
		// Remove previous import overlay (keep submitted/cancelled overlay if present)
		wrap.querySelectorAll(".ppi-import-overlay").forEach(el => el.remove());
		if (!imp) return;

		const ov = document.createElement("div");
		ov.className = imp.ok
			? "ppi-doc-overlay ppi-import-overlay ppi-doc-overlay--imported"
			: "ppi-doc-overlay ppi-import-overlay ppi-doc-overlay--import-error";
		ov.innerHTML = imp.ok
			? `<span class="ppi-doc-overlay-badge">${__("Imported")}</span>`
			: `<span class="ppi-doc-overlay-badge">${__("Import Failed")}</span>` +
			  `<p class="ppi-overlay-error-msg">${frappe.utils.escape_html(imp.error || "")}</p>`;
		wrap.appendChild(ov);
	});

	// Re-render so cells() picks up the new imported state (makes all cells readonly)
	[_hot_fg, _hot_sfg, _hot_mr].forEach(h => { if (h) h.render(); });
}

// ─── Per-PP status helpers ─────────────────────────────────────────────────
// Statuses (shown in sidebar + drive button label):
//   "imported"  — applied successfully, no new edits since
//   "partial"   — applied successfully, but re-edited afterwards (needs re-apply)
//   "pending"   — has unsaved edits, never applied (or failed before any success)
//   "failed"    — last apply errored, no new edits
//   "clean"     — no edits, never attempted

function _get_pp_status(pp_name) {
	const imp    = _pp_imported[pp_name];
	const edited = !!_pp_has_edits[pp_name];

	if (edited)  return imp && imp.ok ? "partial" : "pending";
	if (!imp)    return "clean";
	return imp.ok ? "imported" : "failed";
}

// Update the sidebar badge + data-status for one PP tab (no full re-render).
function _refresh_pp_tab_status(pp_name) {
	if (!_frm_ref) return;
	const status = _get_pp_status(pp_name);
	const labels = {
		imported: __("Fully Imported"),
		partial:  __("Pending Re-apply"),
		pending:  __("Pending Apply"),
		failed:   __("Import Failed"),
		clean:    "",
	};
	const $tab = _frm_ref.fields_dict.importer_layout.$wrapper
		.find(`.ppi-pp-tab[data-pp="${pp_name}"]`);
	if (!$tab.length) return;
	$tab.attr("data-status", status);
	$tab.find(".ppi-pp-tab-status")
		.attr("class", `ppi-pp-tab-status ppi-pp-tab-status--${status}`)
		.find(".ppi-pp-status-text").text(labels[status] || "");
}

function _refresh_all_pp_tab_statuses() {
	Object.keys(_pp_data).forEach(pp => _refresh_pp_tab_status(pp));
}

// Update the primary action button label to match the current PP's status.
function _update_apply_btn() {
	const $btn = _apply_btn;
	if (!$btn || !$btn.length) return;
	if (!_current_pp) {
		$btn.prop("disabled", true).text(__("Apply to Production Plan"));
		return;
	}
	$btn.prop("disabled", false);
	const status = _get_pp_status(_current_pp);
	const labels = {
		imported: __("Re-import"),
		partial:  __("Apply Changes"),
		pending:  __("Apply to Production Plan"),
		failed:   __("Retry Apply"),
		clean:    __("Apply to Production Plan"),
	};
	$btn.text(labels[status] || __("Apply to Production Plan"));
}

// Clear server-side log entries for a single PP after successful apply.
function _clear_pp_log(pp_name) {
	clearTimeout(_log_flush_timer);
	_pending_log_entries = _pending_log_entries.filter(e => e.pp_name !== pp_name);
	if (_pending_log_entries.length) _log_flush_timer = setTimeout(_flush_log, 1500);
	if (!_frm_ref) return;
	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.clear_hot_log",
		args: { pp_names: JSON.stringify([pp_name]) },
	});
}
