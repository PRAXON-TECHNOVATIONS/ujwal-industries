// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on('Bulk Pre Production Plan', {
	refresh: function(frm) {
		// Setup Production Plan items tabs if items are generated
		if (frm.doc.po_items && frm.doc.po_items.length > 0) {
			setTimeout(function() { setup_production_tabs(frm); }, 200);
		}
	},

	get_sales_orders: function(frm) {
		if (!frm.doc.from_delivery_date || !frm.doc.to_delivery_date) {
			frappe.msgprint(__('Please set From Delivery Date and To Delivery Date'));
			return;
		}

		if (!frm.doc.company) {
			frappe.msgprint(__('Please set Company'));
			return;
		}

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_sales_orders',
			args: {
				from_delivery_date: frm.doc.from_delivery_date,
				to_delivery_date: frm.doc.to_delivery_date,
				company: frm.doc.company
			},
			callback: function(r) {
				if (r.message && r.message.sales_orders) {
					// Clear existing sales orders
					frm.clear_table('sales_orders');

					// Add fetched sales orders to the child table
					r.message.sales_orders.forEach(function(so) {
						var row = frm.add_child('sales_orders');
						row.sales_order = so.sales_order;
						row.customer = so.customer;
						row.delivery_date = so.delivery_date;
						row.grand_total = so.grand_total;
						row.status = so.status;
						row.is_selected = so.is_selected;
						row.for_warehouse = so.for_warehouse || 'Stores - UI';
						row.items_generated = so.items_generated;
					});

					// Refresh the sales_orders field to show the data
					frm.refresh_field('sales_orders');

					frappe.show_alert({
						message: __('{0} Sales Orders loaded', [r.message.sales_orders.length]),
						indicator: 'green'
					});
				}
			}
		});
	},

	start_pre_production: function(frm) {
		if (!frm.doc.sales_orders || frm.doc.sales_orders.length === 0) {
			frappe.msgprint(__('No Sales Orders found. Please fetch Sales Orders first.'));
			return;
		}

		const selected_count = (frm.doc.sales_orders || []).filter(row => row.is_selected).length;

		if (selected_count === 0) {
			frappe.msgprint(__('Please select at least one Sales Order'));
			return;
		}

		const planning_mode = frm.doc.custom_planning_mode || 'Sequential';

		frappe.show_alert({ message: __('Generating production plan…'), indicator: 'blue' });

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.generate_production_plan_items',
			args: { docname: frm.doc.name, planning_mode: planning_mode },
			callback(r) {
				if (r.message) {
					frm.reload_doc();
					frappe.show_alert({
						message: __('Pre Production Plan generated successfully!'),
						indicator: 'green'
					});
				}
			}
		});
	}
});

// Child table events for Sales Orders
frappe.ui.form.on('Bulk PP Sales Order', {
	before_sales_orders_remove: function(frm, cdt, cdn) {
		// Store the sales order before it's removed
		const row = locals[cdt][cdn];
		if (row && row.sales_order) {
			// Store it in a temporary variable
			if (!frm._so_to_cleanup) {
				frm._so_to_cleanup = [];
			}
			frm._so_to_cleanup.push(row.sales_order);
		}
	},

	sales_orders_remove: function(frm, cdt, cdn) {
		// Process cleanup after the row is removed
		if (!frm._so_to_cleanup || frm._so_to_cleanup.length === 0) return;

		// Clean up for each removed SO
		frm._so_to_cleanup.forEach(so => {
			cleanup_items_for_sales_order(frm, so);
		});

		// Clear the cleanup queue
		frm._so_to_cleanup = [];
	}
});


function cleanup_items_for_sales_order(frm, sales_order) {
	/**
	 * Remove all items related to a sales order
	 */
	if (!sales_order) return;

	let total_removed = 0;

	// Remove FG items (po_items)
	if (frm.doc.po_items) {
		const items_to_keep = [];
		frm.doc.po_items.forEach((item) => {
			if (item.sales_order === sales_order) {
				frappe.model.clear_doc(item.doctype, item.name);
				total_removed++;
			} else {
				items_to_keep.push(item);
			}
		});
		frm.doc.po_items = items_to_keep;
		frm.refresh_field('po_items');
	}

	// Remove SFG items (sub_assembly_items)
	if (frm.doc.sub_assembly_items) {
		const items_to_keep = [];
		frm.doc.sub_assembly_items.forEach((item) => {
			if (item.sales_order === sales_order) {
				frappe.model.clear_doc(item.doctype, item.name);
				total_removed++;
			} else {
				items_to_keep.push(item);
			}
		});
		frm.doc.sub_assembly_items = items_to_keep;
		frm.refresh_field('sub_assembly_items');
	}

	// Remove MR items (mr_items)
	if (frm.doc.mr_items) {
		const items_to_keep = [];
		frm.doc.mr_items.forEach((item) => {
			if (item.sales_order === sales_order) {
				frappe.model.clear_doc(item.doctype, item.name);
				total_removed++;
			} else {
				items_to_keep.push(item);
			}
		});
		frm.doc.mr_items = items_to_keep;
		frm.refresh_field('mr_items');
	}

	// Show alert
	if (total_removed > 0) {
		frappe.show_alert({
			message: __('Removed {0} items for Sales Order {1}', [total_removed, sales_order]),
			indicator: 'orange'
		}, 5);
	}
}


// ---------------------------------------------------------------------------
// AG Grid display — replaces the old HTML table render functions
// ---------------------------------------------------------------------------

const _AG_ASSETS = [
	'/assets/ujwal_industries/js/vendor/ag-grid-community.min.js',
	'/assets/ujwal_industries/css/vendor/ag-grid.min.css',
	'/assets/ujwal_industries/css/vendor/ag-theme-alpine.min.css',
];

// Grid instance registry keyed by SO name (so we can destroy/recreate on tab switch)
let _grids = {};
let _ag_loaded = false;

function setup_production_tabs(frm) {
	const html_field = frm.fields_dict.production_items_html;
	if (!html_field || !html_field.$wrapper) return;

	const has_items = (frm.doc.po_items || []).length > 0;
	if (!has_items) { html_field.$wrapper.empty(); return; }

	// Build SO map
	const so_map = _build_so_map(frm);
	const so_list = Object.values(so_map);
	if (!so_list.length) return;

	html_field.$wrapper.empty();
	_grids = {};

	// ── mode toolbar ────────────────────────────────────────────────────────
	const mode = frm.doc.custom_planning_mode || 'Sequential';
	const toolbar_html = `
		<div class="bpp-toolbar" style="
			display:flex; align-items:center; gap:14px;
			padding:10px 16px; margin-bottom:14px;
			background:linear-gradient(135deg,#1E293B 0%,#0F172A 100%);
			border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.18);">
			<span style="font-weight:700; font-size:12px; color:#94A3B8; letter-spacing:.08em; text-transform:uppercase;">
				Planning Mode
			</span>
			<div style="display:flex; background:#0F172A; border-radius:6px; padding:3px; gap:2px;">
				<button id="bpp-mode-seq" style="
					padding:5px 14px; border:none; border-radius:4px; font-size:12px; font-weight:600;
					cursor:pointer; transition:all .15s;
					background:${mode==='Sequential'?'#2563EB':'transparent'};
					color:${mode==='Sequential'?'#fff':'#94A3B8'};">
					Sequential
				</button>
				<button id="bpp-mode-par" style="
					padding:5px 14px; border:none; border-radius:4px; font-size:12px; font-weight:600;
					cursor:pointer; transition:all .15s;
					background:${mode==='Parallel'?'#7C3AED':'transparent'};
					color:${mode==='Parallel'?'#fff':'#94A3B8'};">
					⚡ Parallel
				</button>
			</div>
			<button id="bpp-calc-btn" style="
				margin-left:auto; padding:6px 16px; border:none; border-radius:6px;
				background:#059669; color:#fff; font-size:12px; font-weight:600;
				cursor:pointer; display:flex; align-items:center; gap:6px;
				box-shadow:0 1px 4px rgba(5,150,105,.4);">
				<i class="fa fa-refresh" style="font-size:11px;"></i> Calculate Schedule
			</button>
		</div>`;

	// ── SO tabs ──────────────────────────────────────────────────────────────
	let tabs_li = '';
	let tabs_content = '';
	so_list.forEach((so_data, idx) => {
		const active = idx === 0 ? 'active' : '';
		const so_row = (frm.doc.sales_orders || []).find(r => r.sales_order === so_data.so_name) || {};
		const del_date = frappe.format(so_row.delivery_date, {fieldtype:'Date'});
		tabs_li += `
			<li class="nav-item">
				<a class="nav-link bpp-so-tab ${active}" data-so="${so_data.so_name}"
					href="#bpp-so-${idx}" role="tab"
					style="padding:8px 18px; font-size:12px; cursor:pointer;
					border-radius:6px 6px 0 0; font-weight:600; color:${active?'#1E3A5F':'#64748B'};">
					<i class="fa fa-file-text-o" style="margin-right:4px; font-size:11px;"></i>
					${so_data.so_name}
					<span style="display:block; font-size:10px; font-weight:400; color:#94A3B8; margin-top:1px;">
						${so_row.customer || ''} · ${del_date}
					</span>
				</a>
			</li>`;
		tabs_content += `
			<div class="tab-pane fade ${active==='active'?'show active':''}" id="bpp-so-${idx}" role="tabpanel">
				<div class="bpp-grid-wrap" data-so="${so_data.so_name}"
					style="margin-top:0; padding:0;"></div>
			</div>`;
	});

	html_field.$wrapper.html(`
		${toolbar_html}
		<div style="background:#fff; border:1px solid #E2E8F0; border-radius:8px;
			box-shadow:0 1px 4px rgba(0,0,0,.06); overflow:hidden;">
			<ul class="nav nav-tabs" id="bppTabs"
				style="background:#F8FAFC; border-bottom:2px solid #E2E8F0;
				padding:8px 12px 0; margin:0; gap:4px;">${tabs_li}</ul>
			<div class="tab-content" id="bppTabContent"
				style="padding:16px;">${tabs_content}</div>
		</div>
	`);

	// Tab click
	html_field.$wrapper.find('#bppTabs .nav-link').on('click', function(e) {
		e.preventDefault();
		html_field.$wrapper.find('#bppTabs .nav-link').removeClass('active')
			.css({ color: '#64748B', borderBottom: 'none', background: 'transparent' });
		html_field.$wrapper.find('.tab-pane').removeClass('show active');
		$(this).addClass('active')
			.css({ color: '#1E3A5F', borderBottom: '2px solid #2563EB', background: '#EFF6FF' });
		const target = $(this).attr('href');
		html_field.$wrapper.find(target).addClass('show active');
	});

	// Mode buttons
	html_field.$wrapper.find('#bpp-mode-seq').on('click', function() {
		frm.set_value('custom_planning_mode', 'Sequential');
		$(this).css({background:'#2563EB', color:'#fff'});
		html_field.$wrapper.find('#bpp-mode-par').css({background:'transparent', color:'#94A3B8'});
		_render_all_grids(frm, so_map, 'Sequential', html_field.$wrapper);
	});
	html_field.$wrapper.find('#bpp-mode-par').on('click', function() {
		frm.set_value('custom_planning_mode', 'Parallel');
		$(this).css({background:'#7C3AED', color:'#fff'});
		html_field.$wrapper.find('#bpp-mode-seq').css({background:'transparent', color:'#94A3B8'});
		_render_all_grids(frm, so_map, 'Parallel', html_field.$wrapper);
	});

	// Calculate button
	html_field.$wrapper.find('#bpp-calc-btn').on('click', function() {
		_on_calculate_click(frm, so_map, html_field.$wrapper);
	});

	// Initial render
	frappe.require(_AG_ASSETS, function() {
		_ag_loaded = true;
		_render_all_grids(frm, so_map, mode, html_field.$wrapper);
	});
}


function _build_so_map(frm) {
	const map = {};
	(frm.doc.po_items || []).forEach(item => {
		if (!map[item.sales_order]) map[item.sales_order] = { so_name: item.sales_order, fg: [], sfg: [], mr: [] };
		map[item.sales_order].fg.push(item);
	});
	(frm.doc.sub_assembly_items || []).forEach(item => {
		if (map[item.sales_order]) map[item.sales_order].sfg.push(item);
	});
	(frm.doc.mr_items || []).forEach(item => {
		if (map[item.sales_order]) map[item.sales_order].mr.push(item);
	});
	return map;
}


function _on_calculate_click(frm, so_map, $wrapper) {
	const mode = frm.doc.custom_planning_mode || 'Sequential';

	if (mode === 'Sequential') {
		// Sequential: call existing Python calculate_dates_for_sales_order via the
		// same button that already exists, then re-render
		frappe.show_alert({ message: __('Recalculating sequential dates…'), indicator: 'blue' });
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.generate_production_plan_items',
			args: { docname: frm.doc.name },
			callback(r) {
				if (r.message) {
					frm.reload_doc();
					frappe.show_alert({ message: __('Sequential schedule updated'), indicator: 'green' });
				}
			}
		});
	} else {
		// Parallel: call new API, store JSON, re-render
		frappe.show_alert({ message: __('Calculating parallel batch schedule…'), indicator: 'blue' });
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.calculate_parallel_batch_schedule',
			args: { docname: frm.doc.name },
			callback(r) {
				if (r.message) {
					const json_str = JSON.stringify(r.message);
					frm.set_value('custom_batch_schedule', json_str);
					frappe.show_alert({ message: __('Parallel batch schedule calculated'), indicator: 'green' });
					_render_all_grids(frm, so_map, 'Parallel', $wrapper, r.message);
				}
			}
		});
	}
}


function _render_all_grids(frm, so_map, mode, $wrapper, parallel_data) {
	if (!_ag_loaded) {
		frappe.require(_AG_ASSETS, function() {
			_ag_loaded = true;
			_render_all_grids(frm, so_map, mode, $wrapper, parallel_data);
		});
		return;
	}

	// Destroy existing grid instances
	Object.values(_grids).forEach(g => { try { g.destroy(); } catch(e) {} });
	_grids = {};

	// For parallel mode, try stored JSON if no fresh data passed
	let par_data = parallel_data || null;
	if (mode === 'Parallel' && !par_data && frm.doc.custom_batch_schedule) {
		try { par_data = JSON.parse(frm.doc.custom_batch_schedule); } catch(e) {}
	}

	Object.values(so_map).forEach(so_data => {
		const $grid_wrap = $wrapper.find(`.bpp-grid-wrap[data-so="${so_data.so_name}"]`);
		if (!$grid_wrap.length) return;

		if (mode === 'Sequential') {
			_render_sequential_grid(frm, so_data, $grid_wrap[0]);
		} else {
			const so_par = par_data ? par_data[so_data.so_name] : null;
			_render_parallel_grid(frm, so_data, so_par, $grid_wrap[0]);
		}
	});
}


// ---------------------------------------------------------------------------
// Sequential Grid — 1 row per SFG (existing data from sub_assembly_items)
// ---------------------------------------------------------------------------

function _render_sequential_grid(frm, so_data, container) {
	container.innerHTML = '';

	// ── FG section ──────────────────────────────────────────────────────────
	const fg_div = document.createElement('div');
	fg_div.innerHTML = _fg_section_html(so_data.fg);
	container.appendChild(fg_div);

	// ── SFG AG Grid ─────────────────────────────────────────────────────────
	const sfg_label = document.createElement('div');
	sfg_label.innerHTML = _section_header(
		`Sub Assembly Items <span style="font-size:11px;font-weight:400;opacity:.7;">(${so_data.sfg.length} rows)</span>`,
		'#B45309', '#FFFBEB', 'fa-cubes');
	container.appendChild(sfg_label);

	// Color palette per unique bom_level — level 0 first (direct child of FG)
	const _level_colors = ['#D1FAE5','#FEF9C3','#EDE9FE','#FFE4E6','#E0F2FE','#FFF7ED'];
	const _level_border  = ['#059669','#CA8A04','#7C3AED','#E11D48','#0284C7','#EA580C'];
	const _bom_levels = [...new Set((so_data.sfg || []).map(r => r.bom_level))].sort((a,b) => a-b);

	const sfg_el = document.createElement('div');
	sfg_el.className = 'ag-theme-alpine';
	sfg_el.style.cssText = 'height:' + Math.max(200, so_data.sfg.length * 42 + 56) + 'px; width:100%;';
	container.appendChild(sfg_el);

	const sfg_cols = [
		{ headerName: 'Lvl', field: 'bom_level', width: 52, pinned: 'left',
		  sort: 'asc',
		  cellRenderer: p => {
			const li = _bom_levels.indexOf(p.value);
			const bg = _level_border[li % _level_border.length];
			return `<span style="display:inline-block;width:22px;height:22px;line-height:22px;
				text-align:center;border-radius:50%;background:${bg};color:#fff;
				font-size:11px;font-weight:700;">${p.value}</span>`;
		  }
		},
		{ headerName: 'Item Code',   field: 'production_item', width: 140, pinned: 'left',
		  cellRenderer: p => `<strong>${p.value || ''}</strong>` },
		{ headerName: 'Mfg Type',    field: 'type_of_manufacturing', width: 110,
		  cellRenderer: p => _badge(p.value || 'In House', p.value === 'In House' ? '#16a34a' : '#d97706') },
		{ headerName: 'Qty',         field: 'qty',            width: 90,  type: 'numericColumn',
		  valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : '' },
		{ headerName: 'Start Date',  field: 'schedule_date',  width: 130, editable: true,
		  cellStyle: { color: '#0F5132', fontWeight: '600' },
		  valueFormatter: p => p.value ? p.value.toString().split(' ')[0] : '—' },
		{ headerName: 'End Date',    field: 'custom_schedule_end_date', width: 130, editable: true,
		  cellStyle: { color: '#842029', fontWeight: '600' },
		  valueFormatter: p => p.value ? p.value.toString().split(' ')[0] : '—' },
		{ headerName: 'Supplier',    field: 'supplier',       width: 150, editable: true },
		{ headerName: 'Parent Item', field: 'parent_item_code', width: 140 },
		{ headerName: 'BOM',         field: 'bom_no',         width: 160,
		  cellRenderer: p => p.value ? `<code style="font-size:10px;color:#6b7280;background:#f1f5f9;padding:1px 5px;border-radius:3px;">${p.value}</code>` : '' },
	];

	const sfg_grid = agGrid.createGrid(sfg_el, {
		columnDefs: sfg_cols,
		rowData: so_data.sfg,
		defaultColDef: { resizable: true, sortable: true, filter: true },
		suppressMovableColumns: false,
		rowHeight: 38,
		headerHeight: 40,
		getRowStyle: p => {
			if (!p.data) return {};
			const li = _bom_levels.indexOf(p.data.bom_level);
			return { background: _level_colors[li % _level_colors.length] + '99' };
		},
		onCellValueChanged: p => _on_seq_cell_changed(frm, p),
	});
	_grids['seq_sfg_' + so_data.so_name] = sfg_grid;

	// ── MR section ──────────────────────────────────────────────────────────
	_append_mr_section(container, so_data.mr, frm, so_data.so_name, 'seq');
}


function _on_seq_cell_changed(frm, params) {
	// Write edit back to frm.doc child table row
	const row = params.data;
	if (!row || !row.name) return;
	frappe.model.set_value(row.doctype, row.name, params.colDef.field, params.newValue);
}


// ---------------------------------------------------------------------------
// Parallel Grid — N batch rows per SFG with timeline bar column
// ---------------------------------------------------------------------------

function _render_parallel_grid(frm, so_data, par_data, container) {
	container.innerHTML = '';

	if (!par_data) {
		container.innerHTML = `
			<div style="padding:32px 20px; text-align:center; color:#94A3B8; font-size:13px;
				background:#F8FAFC; border-radius:8px; border:1px dashed #CBD5E1;">
				<i class="fa fa-bolt" style="font-size:22px; color:#CBD5E1; display:block; margin-bottom:8px;"></i>
				Click <strong style="color:#6D28D9;">⚡ Parallel</strong> then
				<strong style="color:#059669;">Calculate Schedule</strong> to generate the pipeline batch plan.
			</div>`;
		return;
	}

	// ── FG section ──────────────────────────────────────────────────────────
	const fg_div = document.createElement('div');
	fg_div.innerHTML = _fg_section_html(par_data.fg || so_data.fg);
	container.appendChild(fg_div);

	// ── SFG batch grid ──────────────────────────────────────────────────────
	const total_batches = (par_data.sfg_chain || []).reduce((s, sfg) => s + (sfg.batches || []).length, 0);
	const sfg_label = document.createElement('div');
	sfg_label.innerHTML = _section_header(
		`SFG Batch Schedule — Parallel Pipeline <span style="font-size:11px;font-weight:400;opacity:.7;">(${(par_data.sfg_chain||[]).length} SFGs · ${total_batches} batches)</span>`,
		'#6D28D9', '#F5F3FF', 'fa-sitemap');
	container.appendChild(sfg_label);

	// Display order: parent → child (bom_level 0 = direct child of FG, shown first)
	// sfg_chain from server is deepest-first, so reverse for display
	const chain_display = (par_data.sfg_chain || []).slice().reverse();

	// Custom expand/collapse — AG Grid Community doesn't support masterDetail
	const sfg_colors = ['#2563eb','#d97706','#16a34a','#9333ea','#dc2626','#0891b2'];
	const _expanded  = {};   // item_code → bool

	// Timeline window from all batch dates
	const _all_bt = [];
	chain_display.forEach(sfg => (sfg.batches||[]).forEach(b => {
		if (b.start_date) _all_bt.push(new Date(b.start_date).getTime());
		if (b.end_date)   _all_bt.push(new Date(b.end_date).getTime());
	}));
	const t_min  = _all_bt.length ? Math.min(..._all_bt) : Date.now();
	const t_max  = _all_bt.length ? Math.max(..._all_bt) : Date.now() + 86400000;
	const t_span = t_max - t_min || 1;

	function _build_rows() {
		const rows = [];
		chain_display.forEach((sfg, idx) => {
			const batches = sfg.batches || [];
			const is_exp  = !!_expanded[sfg.item_code];
			rows.push({
				_is_group:     true,
				_expanded:     is_exp,
				_sfg_idx:      idx,
				_row_name:     sfg.row_name,
				item_code:     sfg.item_code,
				bom_no:        sfg.bom_no,
				type:          sfg.type_of_manufacturing,
				supplier:      sfg.supplier,
				total_batches: batches.length,
				total_qty:     batches.reduce((s, b) => s + (b.qty||0), 0),
				per_shift_qty: sfg.per_shift_qty || 0,
				batchsize:     sfg.batchsize || 0,
				start_date:    batches[0]?.start_date || '',
				end_date:      batches[batches.length-1]?.end_date || '',
			});
			if (is_exp) {
				batches.forEach(b => rows.push({
					_is_group:     false,
					_sfg_idx:      idx,
					item_code:     sfg.item_code,
					batch_label:   `${b.batch}/${b.total}`,
					qty:           b.qty,
					mfg_days:      b.mfg_days,
					grn_days:      b.grn_days,
					pm_days:       b.pm_days,
					holiday_count: b.holiday_count || 0,
					start_date:    b.start_date,
					end_date:      b.end_date,
				}));
			}
		});
		return rows;
	}

	const _tl_bar = (p, opacity) => {
		if (!p.data?.start_date || !p.data?.end_date) return '';
		const s = new Date(p.data.start_date).getTime();
		const e = new Date(p.data.end_date).getTime();
		const lp = ((s - t_min) / t_span * 100).toFixed(1);
		const wp = Math.max(((e - s) / t_span * 100), 0.8).toFixed(1);
		const cl = sfg_colors[(p.data._sfg_idx||0) % sfg_colors.length];
		return `<div style="position:relative;width:100%;height:20px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
			<div style="position:absolute;left:${lp}%;width:${wp}%;height:100%;background:${cl};border-radius:3px;opacity:${opacity};"></div>
		</div>`;
	};

	const par_cols = [
		// Chevron toggle
		{ headerName: '', field: '_expanded', width: 36, pinned: 'left', sortable: false,
		  cellStyle: { padding: '0', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' },
		  cellRenderer: p => {
			if (!p.data?._is_group) return '';
			return `<span style="font-size:15px;color:#6b7280;user-select:none;">${p.data._expanded ? '▾' : '▸'}</span>`;
		  },
		  onCellClicked: p => {
			if (!p.data?._is_group) return;
			_expanded[p.data.item_code] = !_expanded[p.data.item_code];
			par_grid.setGridOption('rowData', _build_rows());
		  }
		},
		{ headerName: 'Item Code', field: 'item_code', width: 130, pinned: 'left',
		  cellRenderer: p => {
			if (p.data?._is_group) return p.value ? `<strong>${p.value}</strong>` : '';
			return `<span style="color:#94a3b8;padding-left:10px;">↳ ${p.data?.batch_label || ''}</span>`;
		  }
		},
		{ headerName: 'BOM', field: 'bom_no', width: 150, pinned: 'left',
		  cellRenderer: p => (!p.data?._is_group) ? '' :
			(p.value ? `<small style="color:#6b7280">${p.value}</small>` : '')
		},
		{ headerName: 'Batches', field: 'total_batches', width: 72,
		  cellRenderer: p => {
			if (!p.data?._is_group) return '';
			const cl = sfg_colors[(p.data._sfg_idx||0) % sfg_colors.length];
			return `<span style="background:${cl}22;color:${cl};border:1px solid ${cl}55;border-radius:12px;padding:1px 8px;font-size:11px;font-weight:700;">${p.value}</span>`;
		  }
		},
		{ headerName: 'Qty', width: 95, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,
		  valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{ headerName: 'Mfg Days', width: 82, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? null : p.data?.mfg_days,
		  cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{ headerName: 'GRN Days', width: 82, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? null : p.data?.grn_days,
		  cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{ headerName: 'PM Days', width: 78, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? null : p.data?.pm_days,
		  cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{ headerName: 'Holi.', width: 58, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? null : p.data?.holiday_count,
		  cellStyle: p => (p.value > 0) ? { color:'#dc2626', fontWeight:'bold' } : {},
		  cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{ headerName: 'Per Shift Qty', width: 108, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? p.data.per_shift_qty : null,
		  valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{ headerName: 'SPM', width: 62, type: 'numericColumn',
		  valueGetter: p => p.data?._is_group ? p.data.batchsize : null,
		  cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{ headerName: 'Start Date', field: 'start_date', width: 105,
		  valueFormatter: p => p.value ? p.value.split(' ')[0] : '',
		  cellStyle: p => p.data?._is_group ? { color:'#059669', fontWeight:'600' } : { color:'#059669' }
		},
		{ headerName: 'End Date', field: 'end_date', width: 105,
		  valueFormatter: p => p.value ? p.value.split(' ')[0] : '',
		  cellStyle: p => p.data?._is_group ? { color:'#dc2626', fontWeight:'600' } : { color:'#dc2626' }
		},
		{ headerName: 'Type', field: 'type', width: 108,
		  cellRenderer: p => {
			if (!p.data?._is_group) return '';
			return p.value === 'Subcontract'
				? `<span style="background:#FEF3C7;color:#B45309;border:1px solid #F59E0B55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">SUB</span>`
				: `<span style="background:#DCFCE7;color:#16A34A;border:1px solid #22C55E55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">IN HOUSE</span>`;
		  }
		},
		{ headerName: 'Supplier', field: 'supplier', width: 130,
		  cellRenderer: p => p.data?._is_group ? (p.value || '') : ''
		},
		{ headerName: 'Timeline', flex: 1, minWidth: 200, sortable: false,
		  cellRenderer: p => _tl_bar(p, p.data?._is_group ? '0.85' : '0.45')
		},
	];

	const sfg_el = document.createElement('div');
	sfg_el.className = 'ag-theme-alpine';
	sfg_el.style.cssText = 'width:100%;';
	container.appendChild(sfg_el);

	const par_grid = agGrid.createGrid(sfg_el, {
		columnDefs:    par_cols,
		rowData:       _build_rows(),
		defaultColDef: { resizable: true, sortable: false },
		getRowHeight:  p => p.data?._is_group ? 40 : 34,
		headerHeight:  40,
		domLayout:     'autoHeight',
		getRowStyle:   p => p.data?._is_group
			? { background: '#F8FAFC', fontWeight: '500', borderBottom: '1px solid #e2e8f0' }
			: { background: '#ffffff' },
	});
	_grids['par_' + so_data.so_name] = par_grid;

	// ── MR section ──────────────────────────────────────────────────────────
	_append_mr_section(container, par_data.mr || so_data.mr, frm, so_data.so_name, 'par');
}


function _on_par_cell_changed(frm, params, par_data) {
	// Persist edit back into frm.doc custom_batch_schedule JSON
	if (!params.data || !frm.doc.custom_batch_schedule) return;
	try {
		const schedule = JSON.parse(frm.doc.custom_batch_schedule);
		// find the matching batch and update
		const so_name = params.data._row_name ? _find_so_for_row(schedule, params.data._row_name) : null;
		// simplified: mark dirty so user can save
		frm.dirty();
	} catch(e) {}
}


function _find_so_for_row(schedule, row_name) {
	for (const [so, data] of Object.entries(schedule)) {
		if ((data.sfg_chain || []).some(s => s.row_name === row_name)) return so;
	}
	return null;
}


// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function _fg_section_html(fg_items) {
	if (!fg_items || !fg_items.length) return '';
	const rows = fg_items.map(item => {
		const mfg_type = item.manufacturing_type || item.custom_manufacturing_type || 'In House';
		const badge_color = mfg_type === 'In House' ? '#059669' : '#2563EB';
		const start = (item.planned_start_date || '').split(' ')[0] || '—';
		const end   = (item.custom_planned_end_date || '').split(' ')[0] || '—';
		const qty   = Number(item.planned_qty || item.qty || 0).toLocaleString('en-IN');
		return `
		<tr style="background:#fff; border-bottom:1px solid #EFF6FF;">
			<td style="padding:10px 14px; font-weight:700; color:#1E293B; font-size:13px; white-space:nowrap;">
				<span style="display:inline-flex;align-items:center;gap:6px;">
					<span style="width:8px;height:8px;border-radius:50%;background:#1E40AF;display:inline-block;"></span>
					${item.item_code || ''}
				</span>
			</td>
			<td style="padding:10px 14px; text-align:right; font-variant-numeric:tabular-nums;
				color:#334155; font-weight:600;">${qty}</td>
			<td style="padding:10px 14px;">${_badge(mfg_type, badge_color)}</td>
			<td style="padding:10px 14px;">
				<span style="display:inline-flex;align-items:center;gap:5px;
					background:#ECFDF5;border:1px solid #6EE7B7;border-radius:5px;padding:3px 10px;">
					<i class="fa fa-calendar-o" style="color:#059669;font-size:10px;"></i>
					<span style="color:#065F46;font-weight:700;font-size:12px;">${start}</span>
				</span>
			</td>
			<td style="padding:10px 14px;">
				<span style="display:inline-flex;align-items:center;gap:5px;
					background:#FFF1F2;border:1px solid #FECDD3;border-radius:5px;padding:3px 10px;">
					<i class="fa fa-flag-o" style="color:#E11D48;font-size:10px;"></i>
					<span style="color:#BE123C;font-weight:700;font-size:12px;">${end}</span>
				</span>
			</td>
			<td style="padding:10px 14px;">
				<code style="font-size:10px;color:#6B7280;background:#F1F5F9;
					padding:2px 6px;border-radius:3px;border:1px solid #E2E8F0;">
					${item.bom_no || '—'}
				</code>
			</td>
		</tr>`;
	}).join('');

	return `
		${_section_header(
			`Finished Goods <span style="font-size:11px;font-weight:400;opacity:.7;">(${fg_items.length})</span>`,
			'#1E40AF', '#EFF6FF', 'fa-cube')}
		<div style="background:#fff; border:1px solid #BFDBFE; border-left:4px solid #1E40AF;
			border-radius:0 0 6px 6px; margin-top:0; margin-bottom:16px; overflow:hidden;">
			<table style="width:100%; border-collapse:collapse; font-size:12px;">
				<thead>
					<tr style="background:linear-gradient(90deg,#EFF6FF,#DBEAFE);
						border-bottom:2px solid #BFDBFE;">
						<th style="${_th_style()}">Item Code</th>
						<th style="${_th_style('right')}">Qty</th>
						<th style="${_th_style()}">Mfg Type</th>
						<th style="${_th_style()}">Start Date</th>
						<th style="${_th_style()}">End Date</th>
						<th style="${_th_style()}">BOM</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;
}

function _th_style(align) {
	return `padding:8px 12px; font-size:11px; font-weight:700; color:#1E40AF;
		letter-spacing:.05em; text-transform:uppercase;
		text-align:${align || 'left'}; white-space:nowrap;`;
}

function _section_header(title, color, bg, icon) {
	return `
		<div style="display:flex; align-items:center; gap:8px; margin:16px 0 0;
			padding:8px 14px; background:${bg}; border-left:4px solid ${color};
			border-radius:4px 4px 0 0; border:1px solid ${color}22;
			border-bottom:2px solid ${color};">
			<i class="fa ${icon}" style="color:${color}; font-size:13px;"></i>
			<span style="font-size:12px; font-weight:700; color:${color};
				letter-spacing:.04em; text-transform:uppercase;">${title}</span>
		</div>`;
}


function _append_mr_section(container, mr_items, frm, so_name, prefix) {
	if (!mr_items || !mr_items.length) return;

	const label = document.createElement('div');
	label.innerHTML = _section_header(
		`Raw Material Items <span style="font-size:11px;font-weight:400;opacity:.7;">(${mr_items.length})</span>`,
		'#065F46', '#ECFDF5', 'fa-flask');
	container.appendChild(label);

	const mr_el = document.createElement('div');
	mr_el.className = 'ag-theme-alpine';
	mr_el.style.cssText = 'height:' + Math.max(160, mr_items.length * 40 + 56) + 'px; width:100%;';
	container.appendChild(mr_el);

	const _par = prefix === 'par';
	const mr_cols = [
		{ headerName: 'Item Code', field: 'item_code', width: 130,
		  cellRenderer: p => `<strong>${p.value || ''}</strong>` },
		{ headerName: 'Item Name', field: 'item_name', width: 160,
		  cellRenderer: p => `<span style="color:#64748b;font-size:11px;">${p.data ? (p.data.item_name || p.data.description || '') : ''}</span>` },
		{ headerName: 'Qty', field: _par ? 'qty' : 'quantity', width: 90, type: 'numericColumn',
		  valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : '' },
		{ headerName: 'UOM', field: 'uom', width: 65 },
		...(_par ? [
			{ headerName: 'GRN Days',  field: 'grn_days',  width: 80, type: 'numericColumn' },
			{ headerName: 'Lead Days', field: 'lead_days', width: 85, type: 'numericColumn' },
		] : []),
		{ headerName: 'Order By', field: _par ? 'start_date' : 'custom_start_date',
		  width: 110, editable: true,
		  cellStyle: { color: '#0F5132', fontWeight: '600' },
		  valueFormatter: p => p.value ? p.value.toString().split(' ')[0] : '' },
		{ headerName: 'Receive By', field: _par ? 'end_date' : 'schedule_date',
		  width: 110, editable: true,
		  cellStyle: { color: '#842029', fontWeight: '600' },
		  valueFormatter: p => p.value ? p.value.toString().split(' ')[0] : '' },
		{ headerName: 'Supplier', field: _par ? 'supplier' : 'custom_supplier', width: 150 },
	];

	agGrid.createGrid(mr_el, {
		columnDefs:    mr_cols,
		rowData:       mr_items,
		defaultColDef: { resizable: true, sortable: true, filter: true },
		rowHeight: 36,
		headerHeight: 40,
	});
}


function _badge(text, color) {
	return `<span style="display:inline-flex;align-items:center;gap:3px;
		background:${color}18; color:${color}; border:1px solid ${color}44;
		border-radius:20px; padding:1px 7px; font-size:9px; font-weight:700;
		letter-spacing:.03em; text-transform:uppercase; white-space:nowrap;">
		<span style="width:4px;height:4px;border-radius:50%;background:${color};display:inline-block;"></span>
		${text}</span>`;
}



