// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on('Bulk Pre Production Plan', {

	onload(frm) {
		setTimeout(() => {

			frm.fields_dict['sales_orders'].grid.wrapper.on(
				'blur',
				'input[data-fieldname="delivery_date"]',
				function () {

					let $input = $(this);
					let rowname = $input.closest('[data-name]').attr('data-name');

					if (!rowname) return;

					let row = frappe.get_doc(
						frm.fields_dict.sales_orders.grid.doctype,
						rowname
					);

					let today = frappe.datetime.get_today();

					if (row.delivery_date && row.delivery_date < today) {
						$input.css("border", "4px solid red");
					} else {
						$input.css("border", "");
					}
				}
			);

		}, 200);
	},

	refresh: function (frm) {

		cur_frm.fields_dict["sales_orders"].$wrapper.find('.grid-body .rows').find(".grid-row").each(function (i, item) {
			let row = locals[cur_frm.fields_dict["sales_orders"].grid.doctype][$(item).attr('data-name')];
			let today = frappe.datetime.get_today();
			if (row.delivery_date != null) {
				if (row.delivery_date && row.delivery_date < today) {
					$(item).find('[data-fieldname="delivery_date"]').css({ 'border': "4px solid red" });
				}
				else {
					$(item).find('[data-fieldname="delivery_date"]').css({ 'border': "" });
				}
			}
		});

		frm.refresh_field('sales_orders');
		add_sales_order_filters(frm);

		// Restore Select Items button labels after reload
		setTimeout(() => {
			(frm.doc.sales_orders || []).forEach(so_row => {
				if (!so_row.selected_items) return;
				let selected;
				try { selected = JSON.parse(so_row.selected_items); } catch (_) { return; }
				if (!selected || !selected.length) return;

				// Get total items for this SO from bom_selections to compute total
				const total_for_so = (frm.doc.bom_selections || []).filter(b => b.sales_order === so_row.sales_order).length;
				// Fallback: if bom_selections not loaded yet, just show count
				const label = (total_for_so && selected.length === total_for_so)
					? __('Select Items')
					: __('Items: {0}', [selected.length]);

				const $row = frm.fields_dict['sales_orders'].grid.wrapper
					.find(`.grid-row[data-name="${so_row.name}"]`);
				$row.find('[data-fieldname="select_items_btn"] button').text(label);
			});
		}, 300);

		set_bom_selection_query(frm);

		if ((frm.doc.sales_orders || []).length > 0 && (frm.doc.bom_selections || []).length === 0 && (frm.doc.po_items || []).length === 0) {
			load_bom_selections(frm);
		}


		// Setup Production Plan items tabs if items are generated
		if (frm.doc.po_items && frm.doc.po_items.length > 0) {
			setTimeout(function () { setup_production_tabs(frm); }, 200);
		}

		if (frm.doc.docstatus === 0 && (frm.doc.po_items || []).length > 0) {
			const update_submit_btn = () => {
				const active_tab = frm.fields_dict.production_items_html.$wrapper.find('.bpp-so-tab.active');
				const active_so = active_tab.attr('data-so');
				const so_row = (frm.doc.sales_orders || []).find(r => r.sales_order === active_so) || {};

				if (so_row.custom_pp_created) {
					frm.set_df_property('start_pre_production', 'hidden', 1); // Hide start if already processed
					frm.remove_custom_button(__('Create Production Plan'));
				} else {
					frm.set_df_property('start_pre_production', 'hidden', 0);
					frm.add_custom_button(__('Create Production Plan'), function () {
						const current_tab = frm.fields_dict.production_items_html.$wrapper.find('.bpp-so-tab.active');
						const so_to_process = current_tab.attr('data-so');

						if (!so_to_process) {
							frappe.msgprint(__('No Sales Order selected in tab.'));
							return;
						}

						frappe.confirm(
							__('Create Production Plan for {0}?', [so_to_process]),
							function () {
								frappe.call({
									method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.create_selected_production_plans',
									args: {
										bulk_pp_name: frm.doc.name,
										sales_orders: [so_to_process]
									},
									freeze: true,
									callback: function (r) {
										if (r.message && r.message.length > 0) {
											frappe.show_alert({
												message: __('Production Plan created successfully for {0}', [so_to_process]),
												indicator: 'green'
											});
											frm.reload_doc();
										}
									}
								});
							}
						);
					}).addClass('btn-primary');
				}
			};

			// Run initially after tabs are setup
			setTimeout(update_submit_btn, 500);

			// Listen for tab clicks to update button
			frm.fields_dict.production_items_html.$wrapper.on('click', '.bpp-so-tab', function () {
				setTimeout(update_submit_btn, 100);
			});
		}
	},
	after_save: function (frm) {
		if (!frm._bom_changed || _bom_recalc_inflight) return;

		_bom_recalc_inflight = true;
		_run_bom_change_recalculation(frm);
	},

	get_sales_orders: function (frm) {
		if (!frm.doc.to_delivery_date) {
			frappe.msgprint(__('Please set Till Delivery Date'));
			return;
		}

		if (!frm.doc.company) {
			frappe.msgprint(__('Please set Company'));
			return;
		}

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_sales_orders',
			args: {
				to_delivery_date: frm.doc.to_delivery_date,
				company: frm.doc.company
			},
			callback: function (r) {
				if (r.message && r.message.sales_orders) {
					// Clear existing sales orders
					frm.clear_table('sales_orders');

					// Add fetched sales orders to the child table
					r.message.sales_orders.forEach(function (so) {
						var row = frappe.model.add_child(frm.doc, 'Bulk PP Sales Order', 'sales_orders');
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
					add_sales_order_filters(frm);
					load_bom_selections(frm);

					frappe.show_alert({
						message: __('{0} Sales Orders loaded', [r.message.sales_orders.length]),
						indicator: 'green'
					});
				}
			}
		});
	},

	start_pre_production: function (frm) {
		if (!frm.doc.sales_orders || frm.doc.sales_orders.length === 0) {
			frappe.msgprint(__('No Sales Orders found. Please fetch Sales Orders first.'));
			return;
		}

		const selected_count = (frm.doc.sales_orders || []).filter(row => row.is_selected).length;

		if (selected_count === 0) {
			frappe.msgprint(__('Please select at least one Sales Order'));
			return;
		}

		const _do_generate = () => {
			frappe.show_alert({ message: __('Generating production plan…'), indicator: 'blue' });
			frappe.call({
				method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.generate_production_plan_items',
				args: { docname: frm.doc.name },
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
		};

		if (frm.is_new()) {
			frm.save().then(_do_generate);
		} else {
			_do_generate();
		}
	}
});

// Child table events for Sales Orders
frappe.ui.form.on('Bulk PP Sales Order', {
	select_items_btn: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.sales_order) {
			frappe.msgprint(__('Please set a Sales Order first'));
			return;
		}

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_sales_order_item_bom_rows',
			args: { sales_orders: [row.sales_order] },
			callback(r) {
				if (!r.message || !r.message.length) {
					frappe.msgprint(__('No items found for this Sales Order'));
					return;
				}

				// Deduplicate by item_code, summing qty across multiple SO lines
				const item_map = {};
				r.message.forEach(item => {
					if (item_map[item.item_code]) {
						item_map[item.item_code].qty = (item_map[item.item_code].qty || 0) + (item.qty || 0);
					} else {
						item_map[item.item_code] = Object.assign({}, item);
					}
				});
				const items = Object.values(item_map);

				let already_selected = [];
				try {
					already_selected = row.selected_items ? JSON.parse(row.selected_items) : [];
				} catch (_) { already_selected = []; }

				// Build dialog fields — one Check per unique item_code
				const fields = items.map(item => ({
					fieldtype: 'Check',
					fieldname: item.item_code,
					label: `${item.item_code}  —  ${item.item_name || ''}  (Qty: ${item.qty || ''} ${item.stock_uom || ''})`,
					default: already_selected.length === 0 || already_selected.includes(item.item_code) ? 1 : 0,
				}));

				const d = new frappe.ui.Dialog({
					title: __('Select Items — {0}', [row.sales_order]),
					fields: fields,
					primary_action_label: __('Confirm'),
					primary_action(values) {
						const selected = items
							.filter(item => values[item.item_code])
							.map(item => item.item_code);

						frappe.model.set_value(cdt, cdn, 'selected_items', JSON.stringify(selected));

						// Update button label to show count
						const $btn = frm.fields_dict['sales_orders'].grid.wrapper
							.find(`[data-name="${cdn}"] [data-fieldname="select_items_btn"] button`);
						$btn.text(selected.length === items.length
							? __('Select Items')
							: __('Items: {0}/{1}', [selected.length, items.length]));

						d.hide();
					}
				});

				// Add Select All / Deselect All buttons
				d.$wrapper.find('.modal-header').append(
					`<div style="margin-top:6px;">
						<button class="btn btn-xs btn-default so-select-all">${__('Select All')}</button>
						<button class="btn btn-xs btn-default so-deselect-all" style="margin-left:6px;">${__('Deselect All')}</button>
					</div>`
				);
				d.$wrapper.on('click', '.so-select-all', () => {
					items.forEach(item => d.set_value(item.item_code, 1));
				});
				d.$wrapper.on('click', '.so-deselect-all', () => {
					items.forEach(item => d.set_value(item.item_code, 0));
				});

				d.show();
			}
		});
	},

	before_sales_orders_remove: function (frm, cdt, cdn) {
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

	sales_orders_remove: function (frm, cdt, cdn) {
		// Process cleanup after the row is removed
		if (!frm._so_to_cleanup || frm._so_to_cleanup.length === 0) return;

		// Clean up for each removed SO
		frm._so_to_cleanup.forEach(so => {
			cleanup_items_for_sales_order(frm, so);
		});

		// Clear the cleanup queue
		frm._so_to_cleanup = [];
	},
});


frappe.ui.form.on('Bulk PP BOM Selection', {
	bom_no: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row || !row.bom_no) {
			frappe.model.set_value(cdt, cdn, 'spm', 0);
			return;
		}

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_bom_spm_details',
			args: { bom_no: row.bom_no },
			callback: function (r) {
				frappe.model.set_value(cdt, cdn, 'spm', r.message?.spm || 0);
			}
		});
	}
});


function set_bom_selection_query(frm) {
	if (!frm.fields_dict.bom_selections) return;

	frm.fields_dict.bom_selections.grid.get_field('bom_no').get_query = function (doc, cdt, cdn) {
		const row = locals[cdt][cdn];
		return {
			filters: {
				item: row.item_code,
				is_active: 1,
				docstatus: 1
			}
		};
	};
}


function load_bom_selections(frm) {
	const sales_orders = (frm.doc.sales_orders || []).map(row => row.sales_order).filter(Boolean);
	if (!sales_orders.length) {
		frm.clear_table('bom_selections');
		frm.refresh_field('bom_selections');
		return;
	}

	frappe.call({
		method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_sales_order_item_bom_rows',
		args: {
			sales_orders: sales_orders,
			docname: frm.is_new() ? null : frm.doc.name
		},
		callback: function (r) {
			const rows = r.message || [];
			frm.clear_table('bom_selections');

			// Build a map of SO -> selected item_codes (null means no filter)
			const so_selected_map = {};
			(frm.doc.sales_orders || []).forEach(so_row => {
				if (so_row.selected_items) {
					try {
						so_selected_map[so_row.sales_order] = new Set(JSON.parse(so_row.selected_items));
					} catch (_) {}
				}
			});

			rows.forEach(function (item) {
				// Skip if this SO has a selection and this item is not in it
				const sel = so_selected_map[item.sales_order];
				if (sel && !sel.has(item.item_code)) return;

				const row = frappe.model.add_child(frm.doc, 'Bulk PP BOM Selection', 'bom_selections');
				row.sales_order = item.sales_order;
				row.sales_order_item = item.sales_order_item;
				row.item_code = item.item_code;
				row.item_name = item.item_name;
				row.qty = item.qty;
				row.stock_uom = item.stock_uom;
				row.bom_no = item.bom_no;
				row.spm = item.spm;
			});

			frm.refresh_field('bom_selections');
		}
	});
}


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

	// Remove BOM selections
	if (frm.doc.bom_selections) {
		const items_to_keep = [];
		frm.doc.bom_selections.forEach((item) => {
			if (item.sales_order === sales_order) {
				frappe.model.clear_doc(item.doctype, item.name);
				total_removed++;
			} else {
				items_to_keep.push(item);
			}
		});
		frm.doc.bom_selections = items_to_keep;
		frm.refresh_field('bom_selections');
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
let _bom_options_cache = {};
let _bom_recalc_inflight = false;
let _bom_capacity_cache = {};
let _default_shift_types_cache = null;

function setup_production_tabs(frm) {
	const html_field = frm.fields_dict.production_items_html;
	if (!html_field || !html_field.$wrapper) return;

	const has_items = (frm.doc.po_items || []).length > 0;
	if (!has_items) { html_field.$wrapper.empty(); return; }

	// Build SO map
	const so_map = _build_so_map(frm);
	// console.log("........so_map....",so_map)
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
					background:${mode === 'Sequential' ? '#2563EB' : 'transparent'};
					color:${mode === 'Sequential' ? '#fff' : '#94A3B8'};">
					Sequential
				</button>
				<button id="bpp-mode-par" style="
					padding:5px 14px; border:none; border-radius:4px; font-size:12px; font-weight:600;
					cursor:pointer; transition:all .15s;
					background:${mode === 'Parallel' ? '#7C3AED' : 'transparent'};
					color:${mode === 'Parallel' ? '#fff' : '#94A3B8'};">
					⚡ Parallel
				</button>
				<button id="bpp-mode-consol" style="
					padding:5px 14px; border:none; border-radius:4px; font-size:12px; font-weight:600;
					cursor:pointer; transition:all .15s;
					background:${mode === 'Consolidated' ? '#e3ae1b' : 'transparent'};
					color:${mode === 'Consolidated' ? '#fff' : '#94A3B8'};">
					🔗 Consolidated
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
		const isMerged = so_row.merged == 1;
		const del_date = frappe.format(so_row.delivery_date, { fieldtype: 'Date' });
		tabs_li += `
    
			<li class="nav-item">
				<a class="nav-link bpp-so-tab ${active}" data-so="${so_data.so_name}"
					href="#bpp-so-${idx}" role="tab"
					style="padding:8px 18px; font-size:12px; cursor:pointer;
					border-radius:6px 6px 0 0; font-weight:600; color:${active ? '#1E3A5F' : '#64748B'};
					background:${isMerged ? '#FEF3C7' : ''};
					border:${isMerged ? '1px solid #F59E0B' : ''};"

					<i class="fa ${so_row.custom_pp_created ? 'fa-check-circle' : 'fa-file-text-o'}" 
						style="margin-right:4px; font-size:11px; color:${so_row.custom_pp_created ? '#16A34A' : 'inherit'};"></i>
					${so_data.so_name}
					<span style="display:block; font-size:10px; font-weight:400; color:#94A3B8; margin-top:1px;">
						${so_row.customer || ''} · ${del_date}
					</span>
				</a>
			</li>`;
		tabs_content += `
		<div class="tab-pane fade ${active === 'active' ? 'show active' : ''}" id="bpp-so-${idx}" role="tabpanel">
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
	html_field.$wrapper.find('#bppTabs .nav-link').on('click', function (e) {
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
	html_field.$wrapper.find('#bpp-mode-seq').on('click', function () {
		frm.set_value('custom_planning_mode', 'Sequential');
		$(this).css({ background: '#2563EB', color: '#fff' });
		html_field.$wrapper.find('#bpp-mode-par').css({ background: 'transparent', color: '#94A3B8' });
		html_field.$wrapper.find('#bpp-consol-par').css({ background: 'transparent', color: '#94A3B8' });
		_render_all_grids(frm, so_map, 'Sequential', html_field.$wrapper);
	});
	html_field.$wrapper.find('#bpp-mode-par').on('click', function () {
		frm.set_value('custom_planning_mode', 'Parallel');
		$(this).css({ background: '#7C3AED', color: '#fff' });
		html_field.$wrapper.find('#bpp-mode-seq').css({ background: 'transparent', color: '#94A3B8' });
		html_field.$wrapper.find('#bpp-mode-consol').css({ background: 'transparent', color: '#94A3B8' });
		_render_all_grids(frm, so_map, 'Parallel', html_field.$wrapper);
	});
	html_field.$wrapper.find('#bpp-mode-consol').on('click', function () {
		frm.set_value('custom_planning_mode', 'Consolidated');
		$(this).css({ background: '#e3ae1b', color: '#fff' });
		html_field.$wrapper.find('#bpp-mode-par').css({ background: 'transparent', color: '#94A3B8' });
		html_field.$wrapper.find('#bpp-mode-seq').css({ background: 'transparent', color: '#94A3B8' });
		_render_all_grids(frm, so_map, 'Consolidated', html_field.$wrapper);
	});

	// Calculate button
	html_field.$wrapper.find('#bpp-calc-btn').on('click', function () {
		_on_calculate_click(frm, so_map, html_field.$wrapper);
	});

	// Initial render
	frappe.require(_AG_ASSETS, function () {
		_ag_loaded = true;
		_render_all_grids(frm, so_map, mode, html_field.$wrapper);
	});
}


function _build_so_map(frm) {
	const map = {};
	(frm.doc.po_items || []).forEach(item => {
		if (!map[item.sales_order]) {
			const so_row = (frm.doc.sales_orders || []).find(r => r.sales_order === item.sales_order) || {};
			map[item.sales_order] = {
				so_name: item.sales_order,
				fg: [],
				sfg: [],
				mr: [],
				custom_pp_created: so_row.custom_pp_created
			};
		}
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
	}else if (mode === 'Parallel'){
		// Parallel: recalculate full schedule + apply dates to child rows
		frappe.show_alert({ message: __('Calculating parallel batch schedule…'), indicator: 'blue' });
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.recalculate_existing_schedule',
			args: { docname: frm.doc.name, planning_mode: 'Parallel' },
			callback(r) {
				if (r.message) {
					frappe.show_alert({ message: __('Parallel batch schedule calculated'), indicator: 'green' });
					frm.reload_doc().then(() => {
						const schedule = JSON.parse(frm.doc.custom_batch_schedule || '{}');
						_render_all_grids(frm, _build_so_map(frm), 'Parallel', $wrapper, schedule);
					});
				}
			}
		});
	}
	else {
		let merged_rows = (frm.doc.sales_orders || []).filter(row => row.merged);

		if (merged_rows.length < 2) {
			frappe.msgprint(__('Please select at least 2 rows with "Merged" checked before Consolidated Planning.'));
			return;
		}
		let so_names = merged_rows.map(row => row.sales_order).filter(Boolean);
		
		// consolidated: recalculate full schedule + apply dates to child rows
		frappe.show_alert({ message: __('Calculating consolidated batch schedule…'), indicator: 'blue' });
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.recalculate_existing_schedule',
			args: { docname: frm.doc.name, planning_mode: 'Consolidated' },
			callback(r) {
				if (r.message) {
					frappe.show_alert({ message: __('consolidated batch schedule calculated'), indicator: 'green' });
					frm.reload_doc().then(() => {
						const schedule = JSON.parse(frm.doc.custom_batch_schedule || '{}');
						_render_all_grids(frm, _build_so_map(frm), 'Consolidated', $wrapper, schedule);
					});
				}
			}
		});
	}
}


function _render_all_grids(frm, so_map, mode, $wrapper, parallel_data) {
	if (!_ag_loaded) {
		frappe.require(_AG_ASSETS, function () {
			_ag_loaded = true;
			_render_all_grids(frm, so_map, mode, $wrapper, parallel_data);
		});
		return;
	}

	const item_codes = _collect_bom_item_codes(so_map, mode, parallel_data);
	const missing_item_codes = item_codes.filter(item_code => !_bom_options_cache[item_code]);
	if (missing_item_codes.length) {
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_active_boms_for_items',
			args: { item_codes: missing_item_codes },
			callback(r) {
				Object.assign(_bom_options_cache, r.message || {});
				_render_all_grids(frm, so_map, mode, $wrapper, parallel_data);
			}
		});
		return;
	}

	// Destroy existing grid instances
	Object.values(_grids).forEach(g => { try { g.destroy(); } catch (e) { } });
	_grids = {};

	// For parallel mode, try stored JSON if no fresh data passed
	let par_data = parallel_data || null;
	if (mode === 'Parallel' && !par_data && frm.doc.custom_batch_schedule) {
		try { par_data = JSON.parse(frm.doc.custom_batch_schedule); } catch (e) { }
	}

	
	if (mode === 'Consolidated' && !par_data && frm.doc.custom_batch_schedule) {
		try { par_data = JSON.parse(frm.doc.custom_batch_schedule); } catch (e) { }
	}


	Promise.resolve()
		.then(() => _hydrate_machine_defaults(frm, par_data))
		.then((machine_changed) => {
			if (machine_changed) {
				_render_all_grids(frm, so_map, mode, $wrapper, par_data);
				return null;
			}
			return _hydrate_shift_defaults(frm, par_data);
		})
		.then((shift_changed) => {
			if (shift_changed) {
				_render_all_grids(frm, so_map, mode, $wrapper, par_data);
				return;
			}

			Object.values(so_map).forEach(so_data => {
				const $grid_wrap = $wrapper.find(`.bpp-grid-wrap[data-so="${so_data.so_name}"]`);
				if (!$grid_wrap.length) return;

				if (mode === 'Sequential') {
					_render_sequential_grid(frm, so_data, $grid_wrap[0]);
				} 
				else if(mode == 'Parallel') {
					const so_par = par_data ? par_data[so_data.so_name] : null;
					_render_parallel_grid(frm, so_data, so_par, $grid_wrap[0]);
				}else {
					const so_par = par_data ? par_data[so_data.so_name] : null;
					_render_parallel_grid(frm, so_data, so_par, $grid_wrap[0]);
				}
			});
		});
}


// ---------------------------------------------------------------------------
// Sequential Grid — 1 row per SFG (existing data from sub_assembly_items)
// ---------------------------------------------------------------------------

function _render_sequential_grid(frm, so_data, container) {
	container.innerHTML = '';

	// ── FG section ──────────────────────────────────────────────────────────
	if (so_data.custom_pp_created) {
		const banner = document.createElement('div');
		banner.innerHTML = `
			<div style="background:#DCFCE7; color:#16A34A; padding:12px 20px; text-align:center; 
				font-weight:700; border-radius:8px; margin-bottom:16px; border:1px solid #BBF7D0;
				display:flex; align-items:center; justify-content:center; gap:10px; font-size:14px;">
				<i class="fa fa-check-circle" style="font-size:18px;"></i>
				Production Plan has been created for ${so_data.so_name}. This view is now read-only.
			</div>`;
		container.appendChild(banner);
		container.style.opacity = '0.85';
		container.style.pointerEvents = 'none';
	}

	// ── MR section ──────────────────────────────────────────────────────────
	_append_mr_section(container, so_data.mr, frm, so_data.so_name, 'seq');

	// ── SFG AG Grid ─────────────────────────────────────────────────────────
	const sfg_label = document.createElement('div');
	sfg_label.innerHTML = _section_header(
		`Sub Assembly Items <span style="font-size:11px;font-weight:400;opacity:.7;">(${so_data.sfg.length} rows)</span>`,
		'#B45309', '#FFFBEB', 'fa-cubes');
	container.appendChild(sfg_label);

	// Color palette per unique bom_level — level 0 first (direct child of FG)
	const _level_colors = ['#D1FAE5', '#FEF9C3', '#EDE9FE', '#FFE4E6', '#E0F2FE', '#FFF7ED'];
	const _level_border = ['#059669', '#CA8A04', '#7C3AED', '#E11D48', '#0284C7', '#EA580C'];
	const _bom_levels = [...new Set((so_data.sfg || []).map(r => r.bom_level))].sort((a, b) => a - b);

	const sfg_el = document.createElement('div');
	sfg_el.className = 'ag-theme-alpine';
	sfg_el.style.cssText = 'height:' + Math.max(200, so_data.sfg.length * 42 + 56) + 'px; width:100%;';
	container.appendChild(sfg_el);

	const sfg_cols = [
		{
			headerName: 'Lvl', field: 'bom_level', width: 52, pinned: 'left',
			sort: 'asc',
			cellRenderer: p => {
				const li = _bom_levels.indexOf(p.value);
				const bg = _level_border[li % _level_border.length];
				return `<span style="display:inline-block;width:22px;height:22px;line-height:22px;
				text-align:center;border-radius:50%;background:${bg};color:#fff;
				font-size:11px;font-weight:700;">${p.value}</span>`;
			}
		},
		{
			headerName: 'Item Code', field: 'production_item', width: 140, pinned: 'left',
			cellRenderer: p => `<strong>${p.value || ''}</strong>`
		},
		{
			headerName: 'Mfg Type', field: 'type_of_manufacturing', width: 110,
			editable: true,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: {
				values: ['In House', 'Subcontract', 'In House - Vendor']
			},
			cellRenderer: p => {
				let color = '#16a34a'; // In House
				if (p.value === 'Subcontract') color = '#d97706';
				else if (p.value === 'In House - Vendor') color = '#0284c7';
				return _badge(p.value || 'In House', color);
			}
		},
		{
			headerName: 'Target Warehouse', field: 'fg_warehouse', width: 150,
			cellRenderer: p => p.value || '—'
		},
		{
			headerName: 'Qty', field: 'qty', width: 90, type: 'numericColumn',
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{
			headerName: 'Start Date', field: 'schedule_date', width: 130, editable: true,
			cellStyle: { color: '#0F5132', fontWeight: '600' },
			valueFormatter: p => _format_bpp_date(p.value)
		},
		{
			headerName: 'End Date', field: 'custom_schedule_end_date', width: 130, editable: true,
			cellStyle: { color: '#842029', fontWeight: '600' },
			valueFormatter: p => _format_bpp_date(p.value)
		},
		{ headerName: 'Supplier', field: 'supplier', width: 150, editable: true },
		{ headerName: 'Parent Item', field: 'parent_item_code', width: 140 },
		{
			headerName: 'BOM', field: 'bom_no', width: 180, editable: true,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: _get_bom_options(p.data?.production_item, p.value)
			}),
			valueFormatter: p => p.value || '',
			cellRenderer: p => p.value ? `<code style="font-size:10px;color:#6b7280;background:#f1f5f9;padding:1px 5px;border-radius:3px;">${p.value}</code>` : ''
		},
		{
			headerName: 'Tool', field: 'tool', width: 190, editable: true,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: ((p.data?.tools || []).map(row => row.tool).filter(Boolean))
			}),
			cellRenderer: p => p.value || '<span style="color:#94a3b8;">No Tool</span>'
		},
		{
			headerName: 'Machines', field: 'custom_workstations_csv', width: 340, sortable: false, filter: false,
			editable: true,
			autoHeight: true,
			cellStyle: {
				whiteSpace: 'normal',
				lineHeight: '1.35',
				paddingTop: '6px',
				paddingBottom: '6px'
			},
			cellEditor: WorkstationPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				base_batchsize: p.data?.batchsize || 0,
				frm,
				row_type: 'sfg',
				row_name: p.data?.name || p.data?._row_name || ''
			}),
			cellRenderer: p => _machine_display_html(
				p.value,
				p.data?.batchsize || 0,
				_bom_capacity_cache[p.data?.bom_no || '']?.workstations_csv || ''
			)
		},
		{
			headerName: 'Shifts', field: 'custom_shift_types_csv', width: 240, sortable: false, filter: false,
			editable: true,
			autoHeight: true,
			cellStyle: {
				whiteSpace: 'normal',
				lineHeight: '1.35',
				paddingTop: '6px',
				paddingBottom: '6px'
			},
			cellEditor: ShiftPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				frm,
				row_type: 'sfg',
				row_name: p.data?.name || p.data?._row_name || ''
			}),
			cellRenderer: p => _shift_display_html(p.value)
		},
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

	// ── FG section ──────────────────────────────────────────────────────────
	const fg_div = document.createElement('div');
	fg_div.innerHTML = _fg_section_html(so_data.fg, so_data.so_name);
	container.appendChild(fg_div);
	_bind_fg_bom_selects(frm, fg_div);
	_bind_fg_tool_selects(frm, fg_div);
	_bind_fg_machine_selects(frm, fg_div);
	_bind_fg_shift_selects(frm, fg_div);
	_bind_fg_mfg_type_selects(frm, fg_div);
	_bind_fg_supplier_inputs(frm, fg_div);
}


function _on_seq_cell_changed(frm, params) {
	// Write edit back to frm.doc child table row
	const row = params.data;
	if (!row || !row.name) return;
	const fieldname = params.colDef.field;
	const changed = params.oldValue !== params.newValue;
	const doc_row = _find_bpp_row(frm, row.name, 'sfg') || row;
	if (!fieldname) return;

	if (changed && (fieldname === 'bom_no' || fieldname === 'custom_workstations_csv' || fieldname === 'tool')) {
		_mark_bom_form_dirty(frm);
		doc_row[fieldname] = params.newValue;
	}

	const update_promise = (doc_row.doctype && doc_row.name)
		? frappe.model.set_value(doc_row.doctype, doc_row.name, fieldname, params.newValue)
		: Promise.resolve();

	if (fieldname === 'bom_no' && changed) {
		update_promise.then(() => {
			_handle_bom_change(frm, doc_row.name, params.newValue, 'sfg', { params });
		}).catch(() => {
			_handle_bom_change(frm, doc_row.name, params.newValue, 'sfg', { params });
		});
	} else if (fieldname === 'tool' && changed) {
		update_promise.then(() => {
			_handle_tool_change(frm, doc_row.name, 'sfg', params.newValue, { params });
		}).catch(() => {
			_handle_tool_change(frm, doc_row.name, 'sfg', params.newValue, { params });
		});
	} else if (fieldname === 'custom_workstations_csv' && changed) {
		update_promise.then(() => {
			_handle_workstation_change(frm, doc_row.name, 'sfg', params.newValue, { params });
		}).catch(() => {
			_handle_workstation_change(frm, doc_row.name, 'sfg', params.newValue, { params });
		});
	} else if (fieldname === 'type_of_manufacturing' && changed) {
		update_promise.then(() => {
			if (['Subcontract', 'In House - Vendor'].includes(params.newValue)) {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_default_supplier_for_item',
					args: {
						item_code: doc_row.production_item || doc_row.item_code,
						company: frm.doc.company
					},
					callback: function (r) {
						if (r.message && r.message !== doc_row.supplier) {
							frappe.model.set_value(doc_row.doctype, doc_row.name, 'supplier', r.message).then(() => {
								params.node.setDataValue('supplier', r.message);
							});
						}
					}
				});
			} else if (params.newValue === 'In House') {
				frappe.model.set_value(doc_row.doctype, doc_row.name, 'supplier', '').then(() => {
					params.node.setDataValue('supplier', '');
				});
			}
		});
	}
}


// ---------------------------------------------------------------------------
// Parallel Grid — N batch rows per SFG with timeline bar column
// ---------------------------------------------------------------------------

function _render_parallel_grid(frm, so_data, par_data, container) {
	container.innerHTML = '';

	if (so_data.custom_pp_created) {
		const banner = document.createElement('div');
		banner.innerHTML = `
			<div style="background:#DCFCE7; color:#16A34A; padding:12px 20px; text-align:center; 
				font-weight:700; border-radius:8px; margin-bottom:16px; border:1px solid #BBF7D0;
				display:flex; align-items:center; justify-content:center; gap:10px; font-size:14px;">
				<i class="fa fa-check-circle" style="font-size:18px;"></i>
				Production Plan has been created for ${so_data.so_name}. This view is now read-only.
			</div>`;
		container.appendChild(banner);
		container.style.opacity = '0.85';
		container.style.pointerEvents = 'none';
	}

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




	const total_batche = (par_data.fg || []).reduce((s, fg) => s + (fg.batches || []).length, 0);
	const f_g_label = document.createElement('div');
	const fg_label = document.createElement('div');
	fg_label.setAttribute('data-bpp-section', 'fg');
	fg_label.innerHTML = _section_header(
		`FG Batch Schedule — Parallel Pipeline <span style="font-size:11px;font-weight:400;opacity:.7;"> (${total_batche} batches)</span>`,
		'#6D28D9', '#F5F3FF', 'fa-sitemap');
	container.appendChild(fg_label);

	const fg_chain_display = (par_data.fg || []).slice().reverse();

	const fg_colors = ['#2563eb', '#d97706', '#16a34a', '#9333ea', '#dc2626', '#0891b2'];
	const _expandeds = {};


	// Timeline window from all batch dates
	const _alls_bt = [];
	fg_chain_display.forEach(fg => (fg.batches || []).forEach(b => {
		if (b.start_date) _alls_bt.push(new Date(b.start_date).getTime());
		if (b.end_date) _alls_bt.push(new Date(b.end_date).getTime());
	}));
	const t_mins = _alls_bt.length ? Math.min(..._alls_bt) : Date.now();
	const t_maxs = _alls_bt.length ? Math.max(..._alls_bt) : Date.now() + 86400000;
	const t_spans = t_maxs - t_mins || 1;

	function _builds_rows() {
		const rows = [];
		fg_chain_display.forEach((fg, idx) => {
      
			const batches = fg.batches || [];
			const is_exps = !!_expandeds[fg.item_code];
			const fg_type = fg.manufacturing_type || fg.custom_manufacturing_type || fg.type_of_manufacturing || 'In House';
			const fg_supplier = fg.custom_supplier || fg.supplier || '';
			rows.push({
				_is_group: true,
				_row_table: 'fg',
				_expandeds: is_exps,
				_fg_idx: idx,
				_row_name: fg.row_name,
				item_code: fg.item_code,
				bom_no: fg.bom_no,
				tool: fg.tool || '',
				tools: fg.tools || [],
				custom_workstations_csv: fg.custom_workstations_csv || '',
				custom_shift_types_csv: fg.custom_shift_types_csv || '',
				type: fg_type,
				target_warehouse: fg.target_warehouse || '',
				supplier: fg_supplier,
				supplier_list: fg.supplier_list || [],
				total_batches: batches.length,
				actual_qty: fg.actual_qty,
				planned_qty_as_show: fg.planned_qty_as_show,
				total_qty: batches.reduce((s, b) => s + (b.qty || 0), 0),
				per_shift_qty: fg.per_shift_qty || 0,
				batchsize: fg.batchsize || 0,
				// spm: fg.spm || 0,
				spm: fg.spm_1 || 0,
				start_date: batches[0]?.start_date || '',
				end_date: batches[batches.length - 1]?.end_date || '',
			});
			if (is_exps) {
				batches.forEach(b => rows.push({
					_is_group: false,
					_row_table: 'fg',
					_fg_idx: idx,
					item_code: fg.item_code,
					batch_label: `${b.batch}/${b.total}`,
					qty: b.qty,
					mfg_days: b.mfg_days,
					grn_days: b.grn_days,
					pm_days: b.pm_days,
					holiday_count: b.holiday_count || 0,
					holiday_dates: b.holiday_hover || [],
					start_date: b.start_date,
					mfg_end_date: b.mfg_end_date,
					end_date: b.end_date,
				}));
			}
		});
		return rows;
	}

	const _tl_bars = (p, opacity) => {
		if (!p.data?.start_date || !p.data?.end_date) return '';
		const s = new Date(p.data.start_date).getTime();
		const e = new Date(p.data.end_date).getTime();
		const lp = ((s - t_mins) / t_spans * 100).toFixed(1);
		const wp = Math.max(((e - s) / t_spans * 100), 0.8).toFixed(1);
		const cl = fg_colors[(p.data._fg_idx || 0) % fg_colors.length];
		return `<div style="position:relative;width:100%;height:20px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
			<div style="position:absolute;left:${lp}%;width:${wp}%;height:100%;background:${cl};border-radius:3px;opacity:${opacity};"></div>
		</div>`;
	};


	const par_colss = [
		// Chevron toggle

		{
			headerName: '', field: '_expandeds', width: 36, pinned: 'left', sortable: false,
			cellStyle: { padding: '0', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' },
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				return `<span style="font-size:15px;color:#6b7280;user-select:none;">${p.data._expandeds ? '▾' : '▸'}</span>`;
			},
			onCellClicked: p => {
				if (!p.data?._is_group) return;
				_expandeds[p.data.item_code] = !_expandeds[p.data.item_code];
				par_grids.setGridOption('rowData', _builds_rows());
			}

		},
		{
			headerName: 'Item Code', field: 'item_code', width: 130, pinned: 'left',
			cellRenderer: p => {
				if (p.data?._is_group) return p.value ? `<strong>${p.value}</strong>` : '';
				return `<span style="color:#94a3b8;padding-left:10px;">↳ ${p.data?.batch_label || ''}</span>`;
			}
		},
		{
			headerName: 'BOM', field: 'bom_no', width: 170, pinned: 'left', editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: _get_bom_options(p.data?.item_code, p.value)
			}),
			cellRenderer: p => (!p.data?._is_group) ? '' :
				(p.value ? `<small style="color:#6b7280">${p.value}</small>` : '')
		},
		{
			headerName: 'Tool', field: 'tool', width: 190,

			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',

			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: ((p.data?.tools || []).map(row => row.tool).filter(Boolean))
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.data?.type === 'Subcontract') return '';

				return p.value || '<span style="color:#94a3b8;">No Tool</span>';
			}
		},

		{
			headerName: 'Machines', field: 'custom_workstations_csv', width: 340, sortable: false,
			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',
			autoHeight: true,
			cellStyle: p => {
				if (!p.data?._is_group) return null;

				if (p.data?.type === 'Subcontract') {
					return {
						opacity: 0.4,
						pointerEvents: 'none'
					};
				}
				return {
					whiteSpace: 'normal',
					lineHeight: '1.35',
					paddingTop: '6px',
					paddingBottom: '6px'
				};
			},

			cellEditor: WorkstationPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				base_batchsize: p.data?.batchsize || 0,
				frm,
				row_type: 'fg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				if (p.data?.type === 'Subcontract') return '';
				return _machine_display_html(
					p.value,
					p.data?.batchsize || 0,
					_bom_capacity_cache[p.data?.bom_no || '']?.workstations_csv || ''
				);
			}
		},
		{
			headerName: 'Shifts', field: 'custom_shift_types_csv', width: 240, sortable: false,
			editable: p => !!p.data?._is_group,
			cellEditor: ShiftPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				frm,
				row_type: 'fg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),
			cellRenderer: p => p.data?._is_group ? _shift_display_html(p.value) : ''
		},
		{
			headerName: 'Batches', field: 'total_batches', width: 72,
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				const cl = fg_colors[(p.data._fg_idx || 0) % fg_colors.length];
				return `<span style="background:${cl}22;color:${cl};border:1px solid ${cl}55;border-radius:12px;padding:1px 8px;font-size:11px;font-weight:700;">${p.value}</span>`;
			}
		},
		// {
		// 	headerName: 'Qty', width: 95, type: 'numericColumn',
		// 	valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,
		// 	valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		// },

		{
			headerName: 'Qty',
			width: 95,
			type: 'numericColumn',

			valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,

			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : '',

			cellStyle: p => {
				if (p.data?._is_group && p.data?.actual_qty > 0) {
					return { color: '#2563eb', fontWeight: 'bold', cursor: 'pointer' };
				}
				return {};
			},

			cellRenderer: p => {
				if (!p.data?._is_group) {
					return p.value ? Number(p.value).toLocaleString('en-IN') : '';
				}

				const qty = p.value ? Number(p.value).toLocaleString('en-IN') : '';
				const actual = p.data?.actual_qty || 0;

				if (actual > 0) {
					return `<span class="qty-click">${qty}</span>`;
				}

				return qty;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Qty' || !p.data?._is_group) return;

				const actual = p.data?.actual_qty || 0;
				const total = p.data?.planned_qty_as_show || 0;

				if (!actual && !total) return;

				frappe.msgprint({
					title: 'Stock Details',
					message: `
						Total Planned Qty: <b>${Number(total).toLocaleString('en-IN')}</b><br>
						Available Qty in Default Warehouse: <b>${Number(actual).toLocaleString('en-IN')}</b>
					`,
					indicator: 'blue'
				});
			}
		},



		{
			headerName: 'Mfg Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.mfg_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'GRN Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.grn_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'PM Days', width: 78, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.pm_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},

		{
			headerName: 'Holi.', width: 58, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.holiday_count,

			cellStyle: p => (p.value > 0)
				? { color: '#dc2626', fontWeight: 'bold', cursor: 'pointer' }
				: {},

			cellRenderer: p => {
				if (p.data?._is_group) return '';

				const count = p.data?.holiday_count || 0;
				if (!count) return '';

				return `<span class="holi-click">${count}</span>`;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Holi.' || p.data?._is_group) return;

				const dates = p.data?.holiday_dates || [];

				if (!dates.length) return;

				const formatted_dates = dates.map(d => {
					return d;
				});

				frappe.msgprint({
					title: 'Holiday Dates',
					message: formatted_dates.join('<br>'),
					indicator: 'red'
				});
			}
		},

		{
			headerName: 'Per Shift Qty', width: 108, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? p.data.per_shift_qty : null,
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{
			headerName: 'SPM', width: 80, type: 'numericColumn',
			// valueGetter: p => p.data?._is_group ? _effective_spm_value(p.data) : null,
			valueGetter: p => p.data?._is_group ? p.data.spm : null,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'Start Date', field: 'start_date', width: 130,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#059669', fontWeight: '600' } : { color: '#059669' }
		},
		{
			headerName: 'End Date', width: 130,
			valueGetter: p => p.data?.end_date,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#dc2626', fontWeight: '600' } : { color: '#dc2626' }
		},

		{
			headerName: 'Type', field: 'type', width: 108,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: {
				values: ['In House', 'Subcontract', 'In House - Vendor']
			},
			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.value === 'Subcontract') {
					return `<span style="background:#FEF3C7;color:#B45309;border:1px solid #F59E0B55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">SUB</span>`;
				}
				if (p.value === 'In House - Vendor') {
					return `<span style="background:#E0F2FE;color:#0284C7;border:1px solid #38BDF855;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">VENDOR</span>`;
				}

				return `<span style="background:#DCFCE7;color:#16A34A;border:1px solid #22C55E55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">IN HOUSE</span>`;
			}
		},
		{
			headerName: 'Target Warehouse', field: 'target_warehouse', width: 150,
			cellRenderer: p => p.data?._is_group ? (p.value || '—') : ''
		},

		{
			headerName: 'Supplier', field: 'supplier', width: 160,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: p.data?.supplier_list || []
			}),
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				return p.value || '<span style="color:#94a3b8;">No Supplier</span>';
			}
		},
		{
			headerName: 'Timeline', flex: 1, minWidth: 200, sortable: false,
			cellRenderer: p => _tl_bars(p, p.data?._is_group ? '0.85' : '0.45')
		},
	];

	const fg_el = document.createElement('div');
	fg_el.className = 'ag-theme-alpine';
	fg_el.style.cssText = 'width:100%;';
	container.appendChild(fg_el);

	const par_grids = agGrid.createGrid(fg_el, {
		columnDefs: par_colss,
		rowData: _builds_rows(),
		defaultColDef: { resizable: true, sortable: false },
		getRowHeight: p => p.data?._is_group ? 40 : 34,
		headerHeight: 40,
		domLayout: 'autoHeight',
		getRowStyle: p => p.data?._is_group
			? { background: '#F8FAFC', fontWeight: '500', borderBottom: '1px solid #e2e8f0' }
			: { background: '#ffffff' },
		onCellValueChanged: p => _on_par_bom_changed(frm, p, par_data),
	});
	_grids['par_' + so_data.so_name] = par_grids;





	// ── SFG batch grid ──────────────────────────────────────────────────────
	const total_batches = (par_data.sfg_chain || []).reduce((s, sfg) => s + (sfg.batches || []).length, 0);
	const sfg_label = document.createElement('div');
	sfg_label.innerHTML = _section_header(
		`SFG Batch Schedule — Parallel Pipeline <span style="font-size:11px;font-weight:400;opacity:.7;">(${(par_data.sfg_chain || []).length} SFGs · ${total_batches} batches)</span>`,
		'#6D28D9', '#F5F3FF', 'fa-sitemap');
	container.appendChild(sfg_label);

	// Display order: parent → child (bom_level 0 = direct child of FG, shown first)
	// sfg_chain from server is deepest-first, so reverse for display
	const chain_display = (par_data.sfg_chain || []).slice().reverse();

	// Custom expand/collapse — AG Grid Community doesn't support masterDetail
	const sfg_colors = ['#2563eb', '#d97706', '#16a34a', '#9333ea', '#dc2626', '#0891b2'];
	const _expanded = {};   // item_code → bool

	// Timeline window from all batch dates
	const _all_bt = [];
	chain_display.forEach(sfg => (sfg.batches || []).forEach(b => {
		if (b.start_date) _all_bt.push(new Date(b.start_date).getTime());
		if (b.end_date) _all_bt.push(new Date(b.end_date).getTime());
	}));
	const t_min = _all_bt.length ? Math.min(..._all_bt) : Date.now();
	const t_max = _all_bt.length ? Math.max(..._all_bt) : Date.now() + 86400000;
	const t_span = t_max - t_min || 1;

	function _build_rows() {
		const rows = [];
		chain_display.forEach((sfg, idx) => {
			const batches = sfg.batches || [];
			const is_exp = !!_expanded[sfg.item_code];
			rows.push({
				_is_group: true,
				_expanded: is_exp,
				_sfg_idx: idx,
				_row_name: sfg.row_name,
				item_code: sfg.item_code,
				bom_no: sfg.bom_no,
				tool: sfg.tool || '',
				tools: sfg.tools || [],
				custom_workstations_csv: sfg.custom_workstations_csv || '',
				custom_shift_types_csv: sfg.custom_shift_types_csv || '',
				type: sfg.type_of_manufacturing,
				target_warehouse: sfg.target_warehouse || '',
				supplier: sfg.supplier,
				supplier_list: sfg.supplier_list || [],
				total_batches: batches.length,
				actual_qty: sfg.actual_qty,
				qty_as_show: sfg.qty_as_show,
				total_qty: batches.reduce((s, b) => s + (b.qty || 0), 0),
				per_shift_qty: sfg.per_shift_qty || 0,
				batchsize: sfg.batchsize || 0,
				// spm: sfg.spm || 0,
				spm: sfg.spm_1 || 0,
				start_date: batches[0]?.start_date || '',
				end_date: batches[batches.length - 1]?.end_date || '',
			});
			if (is_exp) {
				batches.forEach(b => rows.push({
					_is_group: false,
					_sfg_idx: idx,
					item_code: sfg.item_code,
					batch_label: `${b.batch}/${b.total}`,
					qty: b.qty,
					mfg_days: b.mfg_days,
					grn_days: b.grn_days,
					pm_days: b.pm_days,
					holiday_count: b.holiday_count || 0,
					holiday_dates: b.holiday_hover || [],
					start_date: b.start_date,
					mfg_end_date: b.mfg_end_date,
					end_date: b.end_date,
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
		const cl = sfg_colors[(p.data._sfg_idx || 0) % sfg_colors.length];
		return `<div style="position:relative;width:100%;height:20px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
			<div style="position:absolute;left:${lp}%;width:${wp}%;height:100%;background:${cl};border-radius:3px;opacity:${opacity};"></div>
		</div>`;
	};

	const par_cols = [
		// Chevron toggle
		{
			headerName: '', field: '_expanded', width: 36, pinned: 'left', sortable: false,
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
		{
			headerName: 'Item Code', field: 'item_code', width: 130, pinned: 'left',
			cellRenderer: p => {
				if (p.data?._is_group) return p.value ? `<strong>${p.value}</strong>` : '';
				return `<span style="color:#94a3b8;padding-left:10px;">↳ ${p.data?.batch_label || ''}</span>`;
			}
		},
		{
			headerName: 'BOM', field: 'bom_no', width: 170, pinned: 'left', editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: _get_bom_options(p.data?.item_code, p.value)
			}),
			cellRenderer: p => (!p.data?._is_group) ? '' :
				(p.value ? `<small style="color:#6b7280">${p.value}</small>` : '')
		},

		{
			headerName: 'Tool', field: 'tool', width: 190,

			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',

			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: ((p.data?.tools || []).map(row => row.tool).filter(Boolean))
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.data?.type === 'Subcontract') return '';

				return p.value || '<span style="color:#94a3b8;">No Tool</span>';
			}
		},

		{
			headerName: 'Machines', field: 'custom_workstations_csv', width: 340, sortable: false,

			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',

			autoHeight: true,

			cellStyle: p => {
				if (!p.data?._is_group) return null;

				if (p.data?.type === 'Subcontract') {
					return {
						opacity: 0.4,
						pointerEvents: 'none'
					};
				}

				return {
					whiteSpace: 'normal',
					lineHeight: '1.35',
					paddingTop: '6px',
					paddingBottom: '6px'
				};
			},

			cellEditor: WorkstationPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				base_batchsize: p.data?.batchsize || 0,
				frm,
				row_type: 'sfg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				if (p.data?.type === 'Subcontract') return '';
				return _machine_display_html(
					p.value,
					p.data?.batchsize || 0,
					_bom_capacity_cache[p.data?.bom_no || '']?.workstations_csv || ''
				);
			}
		},
		{
			headerName: 'Shifts', field: 'custom_shift_types_csv', width: 240, sortable: false,
			editable: p => !!p.data?._is_group,
			cellEditor: ShiftPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				frm,
				row_type: 'sfg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),
			cellRenderer: p => p.data?._is_group ? _shift_display_html(p.value) : ''
		},
		{
			headerName: 'Batches', field: 'total_batches', width: 72,
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				const cl = sfg_colors[(p.data._sfg_idx || 0) % sfg_colors.length];
				return `<span style="background:${cl}22;color:${cl};border:1px solid ${cl}55;border-radius:12px;padding:1px 8px;font-size:11px;font-weight:700;">${p.value}</span>`;
			}
		},
		// {
		// 	headerName: 'Qty', width: 95, type: 'numericColumn',
		// 	valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,
		// 	valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		// },

		{
			headerName: 'Qty',width: 95,type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : '',
			cellStyle: p => {
				if (p.data?._is_group && p.data?.actual_qty > 0) {
					return { color: '#2563eb', fontWeight: 'bold', cursor: 'pointer' };
				}
				return {};
			},

			cellRenderer: p => {
				if (!p.data?._is_group) {
					return p.value ? Number(p.value).toLocaleString('en-IN') : '';
				}

				const qty = p.value ? Number(p.value).toLocaleString('en-IN') : '';
				const actual = p.data?.actual_qty || 0;

				if (actual > 0) {
					return `<span class="qty-click">${qty}</span>`;
				}

				return qty;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Qty' || !p.data?._is_group) return;

				const actual = p.data?.actual_qty || 0;
				const total = p.data?.qty_as_show || 0;

				if (!actual && !total) return;

				frappe.msgprint({
					title: 'Stock Details',
					message: `
						Total Planned Qty: <b>${Number(total).toLocaleString('en-IN')}</b><br>
						Available Qty in Default Warehouse: <b>${Number(actual).toLocaleString('en-IN')}</b>
					`,
					indicator: 'blue'
				});
			}
		},


		{
			headerName: 'Mfg Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.mfg_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'GRN Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.grn_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'PM Days', width: 78, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.pm_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'Holi.', width: 58, type: 'numericColumn',
			valueGetter: p => {
				if (p.data?._is_group) return null;
				if (p.data?.type === 'Subcontract') return 0;
				return p.data?.holiday_count || 0;
			},

			cellStyle: p => (p.value > 0)
				? { color: '#dc2626', fontWeight: 'bold', cursor: 'pointer' }
				: {},

			cellRenderer: p => {
				if (p.data?._is_group) return '';

				const count = p.data?.holiday_count || 0;
				if (!count) return '';

				return `<span class="holi-click">${count}</span>`;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Holi.' || p.data?._is_group) return;
				const dates = p.data?.holiday_dates || [];
				if (!dates.length) return;
				const formatted_dates = dates.map(d => {
					return d;
				});
				frappe.msgprint({
					title: 'Holiday Dates', message: formatted_dates.join('<br>'),
					indicator: 'red'
				});
			}
		},

		{
			headerName: 'Per Shift Qty', width: 108, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? p.data.per_shift_qty : null,
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{
			headerName: 'SPM', width: 80, type: 'numericColumn',
			// valueGetter: p => p.data?._is_group ? _effective_spm_value(p.data) : null,
			valueGetter: p => p.data?._is_group ? p.data.spm : null,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'Start Date', field: 'start_date', width: 130,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#059669', fontWeight: '600' } : { color: '#059669' }
		},
		{
			headerName: 'End Date', width: 130,
			valueGetter: p => p.data?.end_date,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#dc2626', fontWeight: '600' } : { color: '#dc2626' }
		},
		{
			headerName: 'Type', field: 'type', width: 108,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: {
				values: ['In House', 'Subcontract', 'In House - Vendor']
			},
			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.value === 'Subcontract') {
					return `<span style="background:#FEF3C7;color:#B45309;border:1px solid #F59E0B55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">SUB</span>`;
				} else if (p.value === 'In House - Vendor') {
					return `<span style="background:#E0F2FE;color:#0284C7;border:1px solid #38BDF855;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">VENDOR</span>`;
				}

				return `<span style="background:#DCFCE7;color:#16A34A;border:1px solid #22C55E55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">IN HOUSE</span>`;
			}
		},
		{
			headerName: 'Target Warehouse', field: 'target_warehouse', width: 150,
			cellRenderer: p => p.data?._is_group ? (p.value || '—') : ''
		},

		{
			headerName: 'Supplier', field: 'supplier', width: 160,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: p.data?.supplier_list || []
			}),
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				return p.value || '<span style="color:#94a3b8;">No Supplier</span>';
			}
		},
		{
			headerName: 'Timeline', flex: 1, minWidth: 200, sortable: false,
			cellRenderer: p => _tl_bar(p, p.data?._is_group ? '0.85' : '0.45')
		},
	];

	const sfg_el = document.createElement('div');
	sfg_el.className = 'ag-theme-alpine';
	sfg_el.style.cssText = 'width:100%;';
	container.appendChild(sfg_el);

	const par_grid = agGrid.createGrid(sfg_el, {
		columnDefs: par_cols,
		rowData: _build_rows(),
		defaultColDef: { resizable: true, sortable: false },
		getRowHeight: p => p.data?._is_group ? 40 : 34,
		headerHeight: 40,
		domLayout: 'autoHeight',
		getRowStyle: p => p.data?._is_group
			? { background: '#F8FAFC', fontWeight: '500', borderBottom: '1px solid #e2e8f0' }
			: { background: '#ffffff' },
		onCellValueChanged: p => _on_par_bom_changed(frm, p, par_data),
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
	} catch (e) { }
}


// ---------------------------------------------------------------------------
// Consolidated Grid — N batch rows per SFG with timeline bar column
// ---------------------------------------------------------------------------



function _render_parallel_grid(frm, so_data, par_data, container) {
	container.innerHTML = '';
	if (!par_data) {
		container.innerHTML = `
			<div style="padding:32px 20px; text-align:center; color:#94A3B8; font-size:13px;
				background:#F8FAFC; border-radius:8px; border:1px dashed #CBD5E1;">
				<i class="fa fa-bolt" style="font-size:22px; color:#CBD5E1; display:block; margin-bottom:8px;"></i>
				Click <strong style="color:#6D28D9;">🔗 Consolidated</strong> then
				<strong style="color:#059669;">Calculate Schedule</strong> to generate the pipeline batch plan.
			</div>`;
		return;
	}




	const total_batche = (par_data.fg || []).reduce((s, fg) => s + (fg.batches || []).length, 0);
	const f_g_label = document.createElement('div');
	const fg_label = document.createElement('div');
	fg_label.innerHTML = _section_header(
		`FG Batch Schedule — Consolidated Pipeline <span style="font-size:11px;font-weight:400;opacity:.7;"> (${total_batche} batches)</span>`,
		'#6D28D9', '#F5F3FF', 'fa-sitemap');
	container.appendChild(fg_label);

	const fg_chain_display = (par_data.fg || []).slice().reverse();

	const fg_colors = ['#2563eb', '#d97706', '#16a34a', '#9333ea', '#dc2626', '#0891b2'];
	const _expandeds = {}; 


	// Timeline window from all batch dates
	const _alls_bt = [];
	fg_chain_display.forEach(fg => (fg.batches || []).forEach(b => {
		if (b.start_date) _alls_bt.push(new Date(b.start_date).getTime());
		if (b.end_date) _alls_bt.push(new Date(b.end_date).getTime());
	}));
	const t_mins = _alls_bt.length ? Math.min(..._alls_bt) : Date.now();
	const t_maxs = _alls_bt.length ? Math.max(..._alls_bt) : Date.now() + 86400000;
	const t_spans = t_maxs - t_mins || 1;

	function _builds_rows() {
		const rows = [];
		fg_chain_display.forEach((fg, idx) => {
			const batches = fg.batches || [];
			const is_exps = !!_expandeds[fg.item_code];
			const fg_type = fg.manufacturing_type || fg.custom_manufacturing_type || fg.type_of_manufacturing || 'In House';
			const fg_supplier = fg.custom_supplier || fg.supplier || '';
			rows.push({
				_is_group: true,
				_row_table: 'fg',
				_expandeds: is_exps,
				_fg_idx: idx,
				_row_name: fg.row_name,
				item_code: fg.item_code,
				bom_no: fg.bom_no,
				tool: fg.tool || '',
				tools: fg.tools || [],
				custom_workstations_csv: fg.custom_workstations_csv || '',
				custom_shift_types_csv: fg.custom_shift_types_csv || '',
				type: fg_type,
				target_warehouse: fg.target_warehouse || '',
				supplier: fg_supplier,
				supplier_list: fg.supplier_list || [],
				total_batches: batches.length,
				actual_qty: fg.actual_qty,
				planned_qty_as_show: fg.planned_qty_as_show,
				total_qty: batches.reduce((s, b) => s + (b.qty || 0), 0),
				per_shift_qty: fg.per_shift_qty || 0,
				batchsize: fg.batchsize || 0,
				// spm: fg.spm || 0,
				spm: fg.spm_1 || 0,	
				start_date: batches[0]?.start_date || '',
				end_date: batches[batches.length - 1]?.end_date || '',
			});
			if (is_exps) {
				batches.forEach(b => rows.push({
					_is_group: false,
					_row_table: 'fg',
					_fg_idx: idx,
					item_code: fg.item_code,
					batch_label: `${b.batch}/${b.total}`,
					qty: b.qty,
					mfg_days: b.mfg_days,
					grn_days: b.grn_days,
					pm_days: b.pm_days,
					holiday_count: b.holiday_count || 0,
					holiday_dates: b.holiday_hover || [],
					start_date: b.start_date,
					mfg_end_date: b.mfg_end_date,
					end_date: b.end_date,
				}));
			}
		});
		return rows;
	}

	const _tl_bars = (p, opacity) => {
		if (!p.data?.start_date || !p.data?.end_date) return '';
		const s = new Date(p.data.start_date).getTime();
		const e = new Date(p.data.end_date).getTime();
		const lp = ((s - t_mins) / t_spans * 100).toFixed(1);
		const wp = Math.max(((e - s) / t_spans * 100), 0.8).toFixed(1);
		const cl = fg_colors[(p.data._fg_idx || 0) % fg_colors.length];
		return `<div style="position:relative;width:100%;height:20px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
			<div style="position:absolute;left:${lp}%;width:${wp}%;height:100%;background:${cl};border-radius:3px;opacity:${opacity};"></div>
		</div>`;
	};

	
	const par_colss = [
		// Chevron toggle
		
		{
			headerName: '', field: '_expandeds', width: 36, pinned: 'left', sortable: false,
			cellStyle: { padding: '0', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' },
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				return `<span style="font-size:15px;color:#6b7280;user-select:none;">${p.data._expandeds ? '▾' : '▸'}</span>`;
			},
			onCellClicked: p => {
				if (!p.data?._is_group) return;
				_expandeds[p.data.item_code] = !_expandeds[p.data.item_code];
				par_grids.setGridOption('rowData', _builds_rows());
			}

		},
		{
			headerName: 'Item Code', field: 'item_code', width: 130, pinned: 'left',
			cellRenderer: p => {
				if (p.data?._is_group) return p.value ? `<strong>${p.value}</strong>` : '';
				return `<span style="color:#94a3b8;padding-left:10px;">↳ ${p.data?.batch_label || ''}</span>`;
			}
		},
		{
			headerName: 'BOM', field: 'bom_no', width: 170, pinned: 'left', editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: _get_bom_options(p.data?.item_code, p.value)
			}),
			cellRenderer: p => (!p.data?._is_group) ? '' :
				(p.value ? `<small style="color:#6b7280">${p.value}</small>` : '')
		},
		{
			headerName: 'Tool',field: 'tool',width: 190,

			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',

			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: ((p.data?.tools || []).map(row => row.tool).filter(Boolean))
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.data?.type === 'Subcontract') return '';

				return p.value || '<span style="color:#94a3b8;">No Tool</span>';
			}
		},

		{
			headerName: 'Machines',field: 'custom_workstations_csv', width: 340, sortable: false,
			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',
			autoHeight: true,
			cellStyle: p => {
				if (!p.data?._is_group) return null;

				if (p.data?.type === 'Subcontract') {
					return {
						opacity: 0.4,
						pointerEvents: 'none'
					};
				}
				return {
					whiteSpace: 'normal',
					lineHeight: '1.35',
					paddingTop: '6px',
					paddingBottom: '6px'
				};
			},

			cellEditor: WorkstationPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				base_batchsize: p.data?.batchsize || 0,
				frm,
				row_type: 'fg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				if (p.data?.type === 'Subcontract') return '';
				return _machine_display_html(
					p.value,
					p.data?.batchsize || 0,
					_bom_capacity_cache[p.data?.bom_no || '']?.workstations_csv || ''
				);
			}
		},
		{
			headerName: 'Shifts', field: 'custom_shift_types_csv', width: 240, sortable: false,
			editable: p => !!p.data?._is_group,
			cellEditor: ShiftPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				frm,
				row_type: 'fg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),
			cellRenderer: p => p.data?._is_group ? _shift_display_html(p.value) : ''
		},
		{
			headerName: 'Batches', field: 'total_batches', width: 72,
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				const cl = fg_colors[(p.data._fg_idx || 0) % fg_colors.length];
				return `<span style="background:${cl}22;color:${cl};border:1px solid ${cl}55;border-radius:12px;padding:1px 8px;font-size:11px;font-weight:700;">${p.value}</span>`;
			}
		},

		{
			headerName: 'Qty',
			width: 95,
			type: 'numericColumn',

			valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,

			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : '',

			cellStyle: p => {
				if (p.data?._is_group && p.data?.actual_qty > 0) {
					return { color: '#2563eb', fontWeight: 'bold', cursor: 'pointer' };
				}
				return {};
			},

			cellRenderer: p => {
				if (!p.data?._is_group) {
					return p.value ? Number(p.value).toLocaleString('en-IN') : '';
				}

				const qty = p.value ? Number(p.value).toLocaleString('en-IN') : '';
				const actual = p.data?.actual_qty || 0;

				if (actual > 0) {
					return `<span class="qty-click">${qty}</span>`;
				}

				return qty;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Qty' || !p.data?._is_group) return;

				const actual = p.data?.actual_qty || 0;
				const total = p.data?.planned_qty_as_show || 0;

				if (!actual && !total) return;

				frappe.msgprint({
					title: 'Stock Details',
					message: `
						Total Planned Qty: <b>${Number(total).toLocaleString('en-IN')}</b><br>
						Available Qty in Default Warehouse: <b>${Number(actual).toLocaleString('en-IN')}</b>
					`,
					indicator: 'blue'
				});
			}
		},



		{
			headerName: 'Mfg Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.mfg_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'GRN Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.grn_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'PM Days', width: 78, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.pm_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},

		{
			headerName: 'Holi.', width: 58, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.holiday_count,

			cellStyle: p => (p.value > 0)
				? { color: '#dc2626', fontWeight: 'bold', cursor: 'pointer' }
				: {},

			cellRenderer: p => {
				if (p.data?._is_group) return '';

				const count = p.data?.holiday_count || 0;
				if (!count) return '';

				return `<span class="holi-click">${count}</span>`;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Holi.' || p.data?._is_group) return;

				const dates = p.data?.holiday_dates || [];

				if (!dates.length) return;

				const formatted_dates = dates.map(d => {
					return d;
				});

				frappe.msgprint({
					title: 'Holiday Dates',
					message: formatted_dates.join('<br>'),
					indicator: 'red'
				});
			}
		},

		{
			headerName: 'Per Shift Qty', width: 108, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? p.data.per_shift_qty : null,
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{
			headerName: 'SPM', width: 80, type: 'numericColumn',
			// valueGetter: p => p.data?._is_group ? _effective_spm_value(p.data) : null,
			valueGetter: p => p.data?._is_group ? p.data.spm : null,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'Start Date', field: 'start_date', width: 130,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#059669', fontWeight: '600' } : { color: '#059669' }
		},
		{
			headerName: 'End Date', width: 130,
			valueGetter: p => p.data?.end_date,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#dc2626', fontWeight: '600' } : { color: '#dc2626' }
		},

		{
			headerName: 'Type', field: 'type', width: 108,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: {
				values: ['In House', 'Subcontract', 'In House - Vendor']
			},
			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.value === 'Subcontract') {
					return `<span style="background:#FEF3C7;color:#B45309;border:1px solid #F59E0B55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">SUB</span>`;
				}
				if (p.value === 'In House - Vendor') {
					return `<span style="background:#E0F2FE;color:#0284C7;border:1px solid #38BDF855;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">VENDOR</span>`;
				}

				return `<span style="background:#DCFCE7;color:#16A34A;border:1px solid #22C55E55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">IN HOUSE</span>`;
			}
		},
		{
			headerName: 'Target Warehouse', field: 'target_warehouse', width: 150,
			cellRenderer: p => p.data?._is_group ? (p.value || '—') : ''
		},
		
		{
			headerName: 'Supplier', field: 'supplier', width: 160,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: p.data?.supplier_list || []
			}),
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				return p.value || '<span style="color:#94a3b8;">No Supplier</span>';
			}
		},
		{
			headerName: 'Timeline', flex: 1, minWidth: 200, sortable: false,
			cellRenderer: p => _tl_bars(p, p.data?._is_group ? '0.85' : '0.45')
		},
	];

	const fg_el = document.createElement('div');
	fg_el.className = 'ag-theme-alpine';
	fg_el.style.cssText = 'width:100%;';
	container.appendChild(fg_el);

	const par_grids = agGrid.createGrid(fg_el, {
		columnDefs: par_colss,
		rowData: _builds_rows(),
		defaultColDef: { resizable: true, sortable: false },
		getRowHeight: p => p.data?._is_group ? 40 : 34,
		headerHeight: 40,
		domLayout: 'autoHeight',
		getRowStyle: p => p.data?._is_group
			? { background: '#F8FAFC', fontWeight: '500', borderBottom: '1px solid #e2e8f0' }
			: { background: '#ffffff' },
		onCellValueChanged: p => _on_par_bom_changed(frm, p, par_data),
	});
	_grids['par_' + so_data.so_name] = par_grids;
	




	// ── SFG batch grid ──────────────────────────────────────────────────────
	const total_batches = (par_data.sfg_chain || []).reduce((s, sfg) => s + (sfg.batches || []).length, 0);
	const sfg_label = document.createElement('div');
	sfg_label.innerHTML = _section_header(
		`SFG Batch Schedule — Parallel Pipeline <span style="font-size:11px;font-weight:400;opacity:.7;">(${(par_data.sfg_chain || []).length} SFGs · ${total_batches} batches)</span>`,
		'#6D28D9', '#F5F3FF', 'fa-sitemap');
	container.appendChild(sfg_label);

	// Display order: parent → child (bom_level 0 = direct child of FG, shown first)
	// sfg_chain from server is deepest-first, so reverse for display
	const chain_display = (par_data.sfg_chain || []).slice().reverse();

	// Custom expand/collapse — AG Grid Community doesn't support masterDetail
	const sfg_colors = ['#2563eb', '#d97706', '#16a34a', '#9333ea', '#dc2626', '#0891b2'];
	const _expanded = {};   // item_code → bool

	// Timeline window from all batch dates
	const _all_bt = [];
	chain_display.forEach(sfg => (sfg.batches || []).forEach(b => {
		if (b.start_date) _all_bt.push(new Date(b.start_date).getTime());
		if (b.end_date) _all_bt.push(new Date(b.end_date).getTime());
	}));
	const t_min = _all_bt.length ? Math.min(..._all_bt) : Date.now();
	const t_max = _all_bt.length ? Math.max(..._all_bt) : Date.now() + 86400000;
	const t_span = t_max - t_min || 1;

	function _build_rows() {
		const rows = [];
		chain_display.forEach((sfg, idx) => {
			const batches = sfg.batches || [];
			const is_exp = !!_expanded[sfg.item_code];
			rows.push({
				_is_group: true,
				_expanded: is_exp,
				_sfg_idx: idx,
				_row_name: sfg.row_name,
				item_code: sfg.item_code,
				bom_no: sfg.bom_no,
				tool: sfg.tool || '',
				tools: sfg.tools || [],
				custom_workstations_csv: sfg.custom_workstations_csv || '',
				custom_shift_types_csv: sfg.custom_shift_types_csv || '',
				type: sfg.type_of_manufacturing,
				target_warehouse: sfg.target_warehouse || '',
				supplier: sfg.supplier,
				supplier_list: sfg.supplier_list || [],
				total_batches: batches.length,
				actual_qty: sfg.actual_qty,
				qty_as_show: sfg.qty_as_show,
				total_qty: batches.reduce((s, b) => s + (b.qty || 0), 0),
				per_shift_qty: sfg.per_shift_qty || 0,
				batchsize: sfg.batchsize || 0,
				// spm: sfg.spm || 0,
				spm: sfg.spm_1 || 0,
				start_date: batches[0]?.start_date || '',
				end_date: batches[batches.length - 1]?.end_date || '',
			});
			if (is_exp) {
				batches.forEach(b => rows.push({
					_is_group: false,
					_sfg_idx: idx,
					item_code: sfg.item_code,
					batch_label: `${b.batch}/${b.total}`,
					qty: b.qty,
					mfg_days: b.mfg_days,
					grn_days: b.grn_days,
					pm_days: b.pm_days,
					holiday_count: b.holiday_count || 0,
					holiday_dates: b.holiday_hover || [],
					start_date: b.start_date,
					mfg_end_date: b.mfg_end_date,
					end_date: b.end_date,
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
		const cl = sfg_colors[(p.data._sfg_idx || 0) % sfg_colors.length];
		return `<div style="position:relative;width:100%;height:20px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
			<div style="position:absolute;left:${lp}%;width:${wp}%;height:100%;background:${cl};border-radius:3px;opacity:${opacity};"></div>
		</div>`;
	};

	const par_cols = [
		// Chevron toggle
		{
			headerName: '', field: '_expanded', width: 36, pinned: 'left', sortable: false,
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
		{
			headerName: 'Item Code', field: 'item_code', width: 130, pinned: 'left',
			cellRenderer: p => {
				if (p.data?._is_group) return p.value ? `<strong>${p.value}</strong>` : '';
				return `<span style="color:#94a3b8;padding-left:10px;">↳ ${p.data?.batch_label || ''}</span>`;
			}
		},
		{
			headerName: 'BOM', field: 'bom_no', width: 170, pinned: 'left', editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: _get_bom_options(p.data?.item_code, p.value)
			}),
			cellRenderer: p => (!p.data?._is_group) ? '' :
				(p.value ? `<small style="color:#6b7280">${p.value}</small>` : '')
		},

		{
			headerName: 'Tool',field: 'tool',width: 190,

			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',

			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: ((p.data?.tools || []).map(row => row.tool).filter(Boolean))
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.data?.type === 'Subcontract') return '';

				return p.value || '<span style="color:#94a3b8;">No Tool</span>';
			}
		},

		{
			headerName: 'Machines',field: 'custom_workstations_csv', width: 340, sortable: false,

			editable: p => !!p.data?._is_group && p.data?.type !== 'Subcontract',

			autoHeight: true,

			cellStyle: p => {
				if (!p.data?._is_group) return null;

				if (p.data?.type === 'Subcontract') {
					return {
						opacity: 0.4,
						pointerEvents: 'none'
					};
				}

				return {
					whiteSpace: 'normal',
					lineHeight: '1.35',
					paddingTop: '6px',
					paddingBottom: '6px'
				};
			},

			cellEditor: WorkstationPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				base_batchsize: p.data?.batchsize || 0,
				frm,
				row_type: 'sfg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),

			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				if (p.data?.type === 'Subcontract') return '';
				return _machine_display_html(
					p.value,
					p.data?.batchsize || 0,
					_bom_capacity_cache[p.data?.bom_no || '']?.workstations_csv || ''
				);
			}
		},
		{
			headerName: 'Shifts', field: 'custom_shift_types_csv', width: 240, sortable: false,
			editable: p => !!p.data?._is_group,
			cellEditor: ShiftPopupEditor,
			cellEditorPopup: true,
			cellEditorParams: p => ({
				frm,
				row_type: 'sfg',
				row_name: p.data?._row_name || p.data?.name || ''
			}),
			cellRenderer: p => p.data?._is_group ? _shift_display_html(p.value) : ''
		},
		{
			headerName: 'Batches', field: 'total_batches', width: 72,
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				const cl = sfg_colors[(p.data._sfg_idx || 0) % sfg_colors.length];
				return `<span style="background:${cl}22;color:${cl};border:1px solid ${cl}55;border-radius:12px;padding:1px 8px;font-size:11px;font-weight:700;">${p.value}</span>`;
			}
		},
		// {
		// 	headerName: 'Qty', width: 95, type: 'numericColumn',
		// 	valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,
		// 	valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		// },

		{
			headerName: 'Qty',width: 95,type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? p.data.total_qty : p.data?.qty,
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : '',
			cellStyle: p => {
				if (p.data?._is_group && p.data?.actual_qty > 0) {
					return { color: '#2563eb', fontWeight: 'bold', cursor: 'pointer' };
				}
				return {};
			},

			cellRenderer: p => {
				if (!p.data?._is_group) {
					return p.value ? Number(p.value).toLocaleString('en-IN') : '';
				}

				const qty = p.value ? Number(p.value).toLocaleString('en-IN') : '';
				const actual = p.data?.actual_qty || 0;

				if (actual > 0) {
					return `<span class="qty-click">${qty}</span>`;
				}

				return qty;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Qty' || !p.data?._is_group) return;

				const actual = p.data?.actual_qty || 0;
				const total = p.data?.qty_as_show || 0;

				if (!actual && !total) return;

				frappe.msgprint({
					title: 'Stock Details',
					message: `
						Total Planned Qty: <b>${Number(total).toLocaleString('en-IN')}</b><br>
						Available Qty in Default Warehouse: <b>${Number(actual).toLocaleString('en-IN')}</b>
					`,
					indicator: 'blue'
				});
			}
		},


		{
			headerName: 'Mfg Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.mfg_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'GRN Days', width: 82, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.grn_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'PM Days', width: 78, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? null : p.data?.pm_days,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'Holi.', width: 58, type: 'numericColumn',
			valueGetter: p => {
				if (p.data?._is_group) return null;
				if (p.data?.type === 'Subcontract') return 0;
				return p.data?.holiday_count || 0;
			},

			cellStyle: p => (p.value > 0)
				? { color: '#dc2626', fontWeight: 'bold', cursor: 'pointer' }
				: {},

			cellRenderer: p => {
				if (p.data?._is_group) return '';

				const count = p.data?.holiday_count || 0;
				if (!count) return '';

				return `<span class="holi-click">${count}</span>`;
			},

			onCellClicked: p => {
				if (p.colDef.headerName !== 'Holi.' || p.data?._is_group) return;
				const dates = p.data?.holiday_dates || [];
				if (!dates.length) return;
				const formatted_dates = dates.map(d => {
					return d;
				});
				frappe.msgprint({
					title: 'Holiday Dates', message: formatted_dates.join('<br>'),
					indicator: 'red'
				});
			}
		},

		{
			headerName: 'Per Shift Qty', width: 108, type: 'numericColumn',
			valueGetter: p => p.data?._is_group ? p.data.per_shift_qty : null,
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{
			headerName: 'SPM', width: 80, type: 'numericColumn',
			// valueGetter: p => p.data?._is_group ? _effective_spm_value(p.data) : null,
			valueGetter: p => p.data?._is_group ? p.data.spm : null,
			cellRenderer: p => p.value != null ? String(p.value) : ''
		},
		{
			headerName: 'Start Date', field: 'start_date', width: 130,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#059669', fontWeight: '600' } : { color: '#059669' }
		},
		{
			headerName: 'End Date', width: 130,
			valueGetter: p => p.data?.end_date,
			valueFormatter: p => _format_bpp_date(p.value, '', !p.data?._is_group),
			cellStyle: p => p.data?._is_group ? { color: '#dc2626', fontWeight: '600' } : { color: '#dc2626' }
		},
		{
			headerName: 'Type', field: 'type', width: 108,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: {
				values: ['In House', 'Subcontract', 'In House - Vendor']
			},
			cellRenderer: p => {
				if (!p.data?._is_group) return '';

				if (p.value === 'Subcontract') {
					return `<span style="background:#FEF3C7;color:#B45309;border:1px solid #F59E0B55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">SUB</span>`;
				} else if (p.value === 'In House - Vendor') {
					return `<span style="background:#E0F2FE;color:#0284C7;border:1px solid #38BDF855;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">VENDOR</span>`;
				}

				return `<span style="background:#DCFCE7;color:#16A34A;border:1px solid #22C55E55;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;">IN HOUSE</span>`;
			}
		},
		{
			headerName: 'Target Warehouse', field: 'target_warehouse', width: 150,
			cellRenderer: p => p.data?._is_group ? (p.value || '—') : ''
		},
		
		{
			headerName: 'Supplier', field: 'supplier', width: 160,
			editable: p => !!p.data?._is_group,
			cellEditor: 'agSelectCellEditor',
			cellEditorParams: p => ({
				values: p.data?.supplier_list || []
			}),
			cellRenderer: p => {
				if (!p.data?._is_group) return '';
				return p.value || '<span style="color:#94a3b8;">No Supplier</span>';
			}
		},
		{
			headerName: 'Timeline', flex: 1, minWidth: 200, sortable: false,
			cellRenderer: p => _tl_bar(p, p.data?._is_group ? '0.85' : '0.45')
		},
	];

	const sfg_el = document.createElement('div');
	sfg_el.className = 'ag-theme-alpine';
	sfg_el.style.cssText = 'width:100%;';
	container.appendChild(sfg_el);

	const par_grid = agGrid.createGrid(sfg_el, {
		columnDefs: par_cols,
		rowData: _build_rows(),
		defaultColDef: { resizable: true, sortable: false },
		getRowHeight: p => p.data?._is_group ? 40 : 34,
		headerHeight: 40,
		domLayout: 'autoHeight',
		getRowStyle: p => p.data?._is_group
			? { background: '#F8FAFC', fontWeight: '500', borderBottom: '1px solid #e2e8f0' }
			: { background: '#ffffff' },
		onCellValueChanged: p => _on_par_bom_changed(frm, p, par_data),
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
	} catch (e) { }
}



function _find_so_for_row(schedule, row_name) {
	for (const [so, data] of Object.entries(schedule)) {
		if ((data.sfg_chain || []).some(s => s.row_name === row_name)) return so;
		if ((data.fg || []).some(f => f.row_name === row_name)) return so;
	}
	return null;
}

function _sync_parallel_schedule_override(frm, row_name, row_type, patch = {}) {
	if (!frm.doc.custom_batch_schedule || !row_name) return;
	try {
		const schedule = JSON.parse(frm.doc.custom_batch_schedule);
		const so_name = _find_so_for_row(schedule, row_name);
		if (!so_name || !schedule[so_name]) return;
		const collection = row_type === 'fg' ? (schedule[so_name].fg || []) : (schedule[so_name].sfg_chain || []);
		const row = collection.find(item => item.row_name === row_name);
		if (!row) return;
		Object.assign(row, patch || {});
		const jsonStr = JSON.stringify(schedule);
		if (frm.doc.doctype && frm.doc.name) {
			frappe.model.set_value(frm.doc.doctype, frm.doc.name, 'custom_batch_schedule', jsonStr);
		} else {
			frm.doc.custom_batch_schedule = jsonStr;
			frm.dirty();
		}
	} catch (e) { }
}


// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------


function _fg_section_html(fg_items, so_name) {
	if (!fg_items || !fg_items.length) return '';
	const rows = fg_items.map(item => {
		const mfg_type = item.manufacturing_type || item.custom_manufacturing_type || 'In House';
		let badge_color = '#059669';
		if (mfg_type === 'Subcontract') badge_color = '#d97706';
		else if (mfg_type === 'In House - Vendor') badge_color = '#0284c7';
		const start = _format_bpp_date(item.planned_start_date);
		const end = _format_bpp_date(item.custom_planned_end_date);
		const qty = Number(item.planned_qty || item.qty || 0).toLocaleString('en-IN');
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
			<td style="padding:10px 14px;">
				<div style="display:flex; align-items:center; gap:8px;">
					${_badge(mfg_type, badge_color)}
					<select
						class="bpp-fg-mfg-type"
						data-row-name="${frappe.utils.escape_html(item.name || item.row_name || '')}"
						style="min-width:155px;padding:4px 6px;border:1px solid #CBD5E1;border-radius:4px;background:#fff;font-size:12px;color:#475569;"
					>
						<option value="In House"${mfg_type === 'In House' ? ' selected' : ''}>In House</option>
						<option value="Subcontract"${mfg_type === 'Subcontract' ? ' selected' : ''}>Subcontract</option>
						<option value="In House - Vendor"${mfg_type === 'In House - Vendor' ? ' selected' : ''}>In House - Vendor</option>
					</select>
				</div>
			</td>
			<td style="padding:10px 14px;">
				<input
					class="bpp-fg-supplier"
					data-row-name="${frappe.utils.escape_html(item.name || item.row_name || '')}"
					value="${frappe.utils.escape_html(item.custom_supplier || '')}"
					placeholder="Supplier"
					style="min-width:180px;padding:5px 8px;border:1px solid #CBD5E1;border-radius:4px;background:#fff;font-size:12px;color:#334155;"
				/>
			</td>
			<td style="padding:10px 14px; color:#334155; font-weight:600;">
				${item.target_warehouse || '—'}
			</td>
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
				<select
					class="bpp-fg-bom-select"
					data-row-name="${frappe.utils.escape_html(item.name || item.row_name || '')}"
					data-item-code="${frappe.utils.escape_html(item.item_code || '')}"
					data-so-name="${frappe.utils.escape_html(so_name || '')}"
					style="min-width:150px;padding:4px 6px;border:1px solid #CBD5E1;border-radius:4px;background:#fff;font-size:12px;color:#475569;"
				>
					${_render_bom_select_options(item.item_code, item.bom_no)}
				</select>
			</td>
			<td style="padding:10px 14px;">
				<select
					class="bpp-fg-tool-select"
					data-row-name="${frappe.utils.escape_html(item.name || item.row_name || '')}"
					data-bom-no="${frappe.utils.escape_html(item.bom_no || '')}"
					style="border:1px solid #CBD5E1;background:#fff;border-radius:4px;padding:6px 8px;font-size:12px;color:#334155;min-width:300px;max-width:420px;"
				>
					${_render_tool_select_options(item.tools || [], item.tool || '')}
				</select>
			</td>
			<td style="padding:10px 14px; position:relative; overflow:visible;">
				<div
					class="bpp-fg-machine-inline"
					data-row-name="${frappe.utils.escape_html(item.name || item.row_name || '')}"
					data-csv="${frappe.utils.escape_html(item.custom_workstations_csv || '')}"
					style="min-width:200px;cursor:pointer;"
				></div>
			</td>
			<td style="padding:10px 14px; position:relative; overflow:visible;">
				<div
					class="bpp-fg-shift-inline"
					data-row-name="${frappe.utils.escape_html(item.name || item.row_name || '')}"
					data-csv="${frappe.utils.escape_html(item.custom_shift_types_csv || '')}"
					style="min-width:160px;cursor:pointer;"
				></div>
			</td>
		</tr>`;
	}).join('');

	return `
		${_section_header(
		`Finished Goods <span style="font-size:11px;font-weight:400;opacity:.7;">(${fg_items.length})</span>`,
		'#1E40AF', '#EFF6FF', 'fa-cube')}
		<div style="background:#fff; border:1px solid #BFDBFE; border-left:4px solid #1E40AF;
			border-radius:0 0 6px 6px; margin-top:0; margin-bottom:16px; overflow:visible;">
			<table style="width:100%; border-collapse:collapse; font-size:12px;">
				<thead>
					<tr style="background:linear-gradient(90deg,#EFF6FF,#DBEAFE);
						border-bottom:2px solid #BFDBFE;">
						<th style="${_th_style()}">Item Code</th>
						<th style="${_th_style('right')}">Qty</th>
						<th style="${_th_style()}">Mfg Type</th>
						<th style="${_th_style()}">Supplier</th>
						<th style="${_th_style()}">Target Warehouse</th>
						<th style="${_th_style()}">Start Date</th>
						<th style="${_th_style()}">End Date</th>
						<th style="${_th_style()}">BOM</th>
						<th style="${_th_style()}">Tool</th>
						<th style="${_th_style()}">Machines</th>
						<th style="${_th_style()}">Shifts</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;
}

function _bind_fg_mfg_type_selects(frm, wrapper) {
	$(wrapper).find('.bpp-fg-mfg-type').off('change').on('change', function () {
		const row_name = $(this).data('row-name');
		const new_type = $(this).val();
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row || !new_type || row.manufacturing_type === new_type) return;

		frappe.model.set_value(row.doctype, row.name, 'manufacturing_type', new_type).then(() => {
			_sync_parallel_schedule_override(frm, row.name, 'fg', { manufacturing_type: new_type });

			// Auto-fetch/clear supplier like SFG planner behavior
			if (['Subcontract', 'In House - Vendor'].includes(new_type)) {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_default_supplier_for_item',
					args: { item_code: row.item_code, company: frm.doc.company },
					callback: function (r) {
						if (r.message && r.message !== row.custom_supplier) {
							frappe.model.set_value(row.doctype, row.name, 'custom_supplier', r.message).then(() => {
								$(wrapper).find(`.bpp-fg-supplier[data-row-name="${row.name}"]`).val(r.message);
								_sync_parallel_schedule_override(frm, row.name, 'fg', { custom_supplier: r.message });
							});
						}
					}
				});
			} else {
				frappe.model.set_value(row.doctype, row.name, 'custom_supplier', '').then(() => {
					$(wrapper).find(`.bpp-fg-supplier[data-row-name="${row.name}"]`).val('');
					_sync_parallel_schedule_override(frm, row.name, 'fg', { custom_supplier: '' });
				});
			}
		});
	});
}

function _bind_fg_supplier_inputs(frm, wrapper) {
	$(wrapper).find('.bpp-fg-supplier').off('change blur').on('change blur', function () {
		const row_name = $(this).data('row-name');
		const new_supplier = ($(this).val() || '').trim();
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row || row.custom_supplier === new_supplier) return;

		frappe.model.set_value(row.doctype, row.name, 'custom_supplier', new_supplier).then(() => {
			_sync_parallel_schedule_override(frm, row.name, 'fg', { custom_supplier: new_supplier });
		});
	});
}

function _collect_bom_item_codes(so_map, mode, parallel_data) {
	const item_codes = new Set();
	Object.values(so_map || {}).forEach(so_data => {
		(so_data.fg || []).forEach(row => row.item_code && item_codes.add(row.item_code));
		(so_data.sfg || []).forEach(row => row.production_item && item_codes.add(row.production_item));
	});
	if (mode === 'Parallel' && parallel_data) {
		Object.values(parallel_data || {}).forEach(so_data => {
			(so_data.fg || []).forEach(row => row.item_code && item_codes.add(row.item_code));
			(so_data.sfg_chain || []).forEach(row => row.item_code && item_codes.add(row.item_code));
		});
	}
	return Array.from(item_codes);
}

function _collect_rows_missing_machine_defaults(frm, parallel_data) {
	const rows = [];
	(frm.doc.po_items || []).forEach(row => {
		if (row.bom_no) rows.push(row);
	});
	(frm.doc.sub_assembly_items || []).forEach(row => {
		if (row.bom_no) rows.push(row);
	});
	if (parallel_data) {
		Object.values(parallel_data || {}).forEach(so_data => {
			(so_data.fg || []).forEach(row => {
				if (row.bom_no) rows.push(row);
			});
			(so_data.sfg_chain || []).forEach(row => {
				if (row.bom_no) rows.push(row);
			});
		});
	}
	return rows;
}

function _hydrate_machine_defaults(frm, parallel_data) {
	const missing_rows = _collect_rows_missing_machine_defaults(frm, parallel_data);
	const bom_nos = Array.from(new Set(missing_rows.map(row => row.bom_no).filter(Boolean)));
	const pending = bom_nos.filter(bom_no => !_bom_capacity_cache[bom_no]);
	if (!pending.length) {
		let changed = false;
		missing_rows.forEach(row => {
			const details = _bom_capacity_cache[row.bom_no];
			if (!details) return;
			if (!row.custom_workstations_csv && details.workstations_csv) {
				row.custom_workstations_csv = details.workstations_csv;
				changed = true;
			}
			if (!row.tool && details.tool) {
				row.tool = details.tool;
				changed = true;
			}
			const effectiveCsv = row.custom_workstations_csv || details.workstations_csv || '';
			const machineCount = _parse_csv_list(effectiveCsv).length || details.machine_count || 0;
			const batchsize = Number(details.batchsize || row.batchsize || 0);
			const shiftCount = _shift_count_from_row(row);
			row.tools = details.tools || row.tools || [];
			row.batchsize = batchsize || row.batchsize || 0;
			row.tool_load_qty = details.tool_load_qty || row.tool_load_qty || 0;
			row.pm_days = details.pm_days || row.pm_days || 0;
			row.machine_count = machineCount;
			row.spm = batchsize > 0 ? (batchsize * machineCount * shiftCount) : (details.spm || row.spm || 0);
		});
		return Promise.resolve(changed);
	}

	return Promise.all(pending.map(bom_no => get_bom_details(bom_no))).then(results => {
		results.forEach(details => {
			if (details?.bom_no) {
				_bom_capacity_cache[details.bom_no] = details;
			}
		});
		return _hydrate_machine_defaults(frm, parallel_data);
	});
}

function _fetch_default_shift_types() {
	if (_default_shift_types_cache && Array.isArray(_default_shift_types_cache)) {
		return Promise.resolve(_default_shift_types_cache);
	}
	return frappe.call({
		method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_default_planning_shift_types',
	}).then(r => {
		_default_shift_types_cache = (r.message || []).filter(Boolean);
		return _default_shift_types_cache;
	}).catch(() => {
		_default_shift_types_cache = [];
		return _default_shift_types_cache;
	});
}

function _collect_rows_missing_shift_defaults(frm, parallel_data) {
	const rows = [];
	(frm.doc.po_items || []).forEach(row => { rows.push({ row, row_type: 'fg' }); });
	(frm.doc.sub_assembly_items || []).forEach(row => { rows.push({ row, row_type: 'sfg' }); });
	if (parallel_data) {
		Object.values(parallel_data || {}).forEach(so_data => {
			(so_data.fg || []).forEach(row => rows.push({ row, row_type: 'fg', from_schedule: true }));
			(so_data.sfg_chain || []).forEach(row => rows.push({ row, row_type: 'sfg', from_schedule: true }));
		});
	}
	return rows;
}

function _hydrate_shift_defaults(frm, parallel_data) {
	const candidates = _collect_rows_missing_shift_defaults(frm, parallel_data);
	return _fetch_default_shift_types().then(defaults => {
		const default_csv = (defaults || []).join(',');
		if (!default_csv) return false;

		let changed = false;
		const updates = [];

		candidates.forEach(({ row, row_type, from_schedule }) => {
			if (!row) return;
			if (row.custom_shift_types_csv) return;
			row.custom_shift_types_csv = default_csv;
			changed = true;

			// Recompute SPM using shifts as multiplier (default shift count >= 1).
			const machine_count = Number(row.machine_count || _parse_csv_list(row.custom_workstations_csv).length || 0);
			const batchsize = Number(row.batchsize || 0);
			const shift_count = _shift_count_from_row(row);
			const spm = batchsize * machine_count * shift_count;
			if (spm) row.spm = spm;

			// Persist to DB for actual child rows (so Save keeps it)
			if (!from_schedule && row.doctype && row.name) {
				updates.push(
					frappe.model.set_value(row.doctype, row.name, 'custom_shift_types_csv', default_csv)
				);
				updates.push(
					frappe.model.set_value(row.doctype, row.name, 'spm', spm)
				);
			}

			// Keep parallel JSON in sync (no DB write here; it’s stored on parent)
			if (from_schedule && row.row_name) {
				_sync_parallel_schedule_override(frm, row.row_name, row_type, { custom_shift_types_csv: default_csv, spm });
			}
		});

		if (!changed) return false;
		_mark_form_dirty(frm);

		if (!updates.length) return true;
		return Promise.allSettled(updates).then(() => true);
	});
}

function _parse_csv_list(csv_value) {
	if (!csv_value) return [];
	return String(csv_value)
		.split(',')
		.map(value => value.trim())
		.filter(Boolean);
}

function _shift_count_from_row(data) {
	const csv = data?.custom_shift_types_csv || '';
	const count = _parse_csv_list(csv).length;
	return count > 0 ? count : 1;
}

function _machine_button_label(csv_value) {
	const values = _parse_csv_list(csv_value);
	if (!values.length) return 'Select';
	return values.join(', ');
}

function _machine_summary_html(batchsize, csv_value) {
	const count = _parse_csv_list(csv_value).length;
	// Default shift multiplier = 1 if shift selection not present yet
	const spm = Number(batchsize || 0) * count;
	return `<div style="margin-top:4px;font-size:10px;color:#64748b;white-space:nowrap;">
		<span>Machines: <strong>${count}</strong></span>
		<span style="margin-left:6px;">SPM: <strong>${spm}</strong></span>
	</div>`;
}

function _get_selected_tool_row(tools, selected_tool) {
	const rows = Array.isArray(tools) ? tools : [];
	return rows.find(row => (row?.tool || '') === (selected_tool || '')) || null;
}

function _effective_spm_value(data) {
	if (!data) return 0;
	const direct_spm = Number(data.spm || 0);
	if (direct_spm > 0) return direct_spm;
	const base_batchsize = Number(data.batchsize || 0);
	const machine_count = Number(data.machine_count || _parse_csv_list(data.custom_workstations_csv).length || 0);
	const shift_count = _shift_count_from_row(data);
	return base_batchsize * machine_count * shift_count;
}

function _find_bpp_row(frm, row_name, row_type) {
	return row_type === 'fg'
		? (frm.doc.po_items || []).find(item => item.name === row_name || item.row_name === row_name)
		: (frm.doc.sub_assembly_items || []).find(item => item.name === row_name || item.row_name === row_name);
}

/* ── Tag / pill styles shared by all inline machine editors ─────────── */
const _TAG_STYLE = 'display:inline-flex;align-items:center;gap:3px;background:#EFF6FF;border:1px solid #BFDBFE;border-radius:12px;padding:2px 8px 2px 10px;font-size:11px;color:#1E40AF;font-weight:500;white-space:nowrap;margin:2px;';
const _TAG_REMOVE_STYLE = 'cursor:pointer;border:none;background:none;color:#3B82F6;font-size:13px;line-height:1;padding:0 1px;font-weight:700;';
const _TAG_INPUT_STYLE = 'border:none;outline:none;font-size:12px;color:#334155;min-width:90px;flex:1;padding:4px 2px;background:transparent;';
const _TAG_WRAPPER_STYLE = 'display:flex;flex-wrap:wrap;align-items:center;border:1px solid #CBD5E1;border-radius:6px;background:#fff;padding:3px 4px;min-height:32px;cursor:text;position:relative;box-sizing:border-box;';
const _DROPDOWN_STYLE = 'position:absolute;left:0;right:0;top:100%;z-index:100;background:#fff;border:1px solid #CBD5E1;border-top:none;border-radius:0 0 6px 6px;max-height:180px;overflow-y:auto;box-shadow:0 8px 20px rgba(15,23,42,.12);';
const _DROPDOWN_ITEM_STYLE = 'padding:7px 12px;font-size:12px;color:#334155;cursor:pointer;';
const _DROPDOWN_ITEM_HOVER = 'background:#EFF6FF;color:#1E40AF;';

function _render_machine_tags(values) {
	if (!values.length) return '';
	return values.map(v =>
		`<span class="bpp-machine-tag" data-value="${frappe.utils.escape_html(v)}" style="${_TAG_STYLE}">
			${frappe.utils.escape_html(v)}
			<button type="button" class="bpp-machine-tag-remove" data-value="${frappe.utils.escape_html(v)}" style="${_TAG_REMOVE_STYLE}" title="Remove">&times;</button>
		</span>`
	).join('');
}

function _machine_display_html(csv_value, batchsize, fallback_csv = '') {
	const effective_csv = csv_value || fallback_csv || '';
	const values = _parse_csv_list(effective_csv);
	const label = values.length ? values.join(', ') : 'Select';
	return `<div style="height:100%;display:flex;align-items:center;width:100%;">
		<div title="${frappe.utils.escape_html(label)}" style="border:1px solid #CBD5E1;background:#fff;border-radius:4px;padding:6px 8px;font-size:12px;color:#334155;width:100%;text-align:left;box-sizing:border-box;white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-height:1.35;">
			${frappe.utils.escape_html(label)}
		</div>
	</div>`;
}

function _shift_display_html(csv_value) {
	const values = _parse_csv_list(csv_value || '');
	const label = values.length ? values.join(', ') : 'Select';
	return `<div style="height:100%;display:flex;align-items:center;width:100%;">
		<div title="${frappe.utils.escape_html(label)}" style="border:1px solid #CBD5E1;background:#fff;border-radius:4px;padding:6px 8px;font-size:12px;color:#334155;width:100%;text-align:left;box-sizing:border-box;white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-height:1.35;">
			${frappe.utils.escape_html(label)}
		</div>
	</div>`;
}

function _get_workstation_options(txt) {
	return _get_link_options('Workstation', txt);
}

function _get_shift_type_options(txt) {
	return _get_link_options('Shift Type', txt);
}

function _get_link_options(doctype, txt) {
	return frappe.call({
		method: 'frappe.desk.search.search_link',
		args: {
			doctype,
			txt: txt || '',
			page_length: 50
		}
	}).then(r => (r.message || []).map(option => option.value || option.name || option));
}

/**
 * Creates a reusable inline tag autocomplete widget.
 * Returns { el, getValues, destroy } where el is the DOM element to mount.
 * onchange(csv_string) is called on every add/remove.
 */
function _create_inline_tag_editor(initial_csv, onchange) {
	const wrapper = document.createElement('div');
	wrapper.style.cssText = _TAG_WRAPPER_STYLE;

	const tagsContainer = document.createElement('span');
	tagsContainer.style.cssText = 'display:contents;';
	wrapper.appendChild(tagsContainer);

	const input = document.createElement('input');
	input.type = 'text';
	input.placeholder = 'Type to add…';
	input.style.cssText = _TAG_INPUT_STYLE;
	input.setAttribute('autocomplete', 'off');
	wrapper.appendChild(input);

	const dropdown = document.createElement('div');
	dropdown.style.cssText = _DROPDOWN_STYLE;
	dropdown.style.display = 'none';
	wrapper.appendChild(dropdown);

	let selected = _parse_csv_list(initial_csv);
	let options = [];
	let highlightIdx = -1;
	let _searchTimeout = null;
	let _destroyed = false;

	function _renderTags() {
		tagsContainer.innerHTML = _render_machine_tags(selected);
		tagsContainer.querySelectorAll('.bpp-machine-tag-remove').forEach(btn => {
			btn.addEventListener('click', (e) => {
				e.stopPropagation();
				const val = btn.getAttribute('data-value');
				selected = selected.filter(v => v !== val);
				_renderTags();
				_fireChange();
			});
		});
		if (!selected.length) {
			input.placeholder = 'Type to add…';
		} else {
			input.placeholder = '';
		}
	}

	function _fireChange() {
		if (onchange) onchange(selected.join(','));
	}

	function _renderDropdown() {
		const filtered = options.filter(o => !selected.includes(o));
		if (!filtered.length || _destroyed) {
			dropdown.style.display = 'none';
			dropdown.innerHTML = '';
			return;
		}
		highlightIdx = Math.min(highlightIdx, filtered.length - 1);
		dropdown.innerHTML = filtered.map((o, i) => {
			const hl = i === highlightIdx ? _DROPDOWN_ITEM_HOVER : '';
			return `<div class="bpp-machine-dd-item" data-value="${frappe.utils.escape_html(o)}" style="${_DROPDOWN_ITEM_STYLE}${hl}">${frappe.utils.escape_html(o)}</div>`;
		}).join('');
		dropdown.style.display = 'block';
		dropdown.querySelectorAll('.bpp-machine-dd-item').forEach(item => {
			item.addEventListener('mousedown', (e) => {
				e.preventDefault();
				const val = item.getAttribute('data-value');
				if (val && !selected.includes(val)) {
					selected.push(val);
					_renderTags();
					_fireChange();
				}
				input.value = '';
				_searchOptions('');
				input.focus();
			});
			item.addEventListener('mouseenter', () => {
				item.style.background = '#EFF6FF';
				item.style.color = '#1E40AF';
			});
			item.addEventListener('mouseleave', () => {
				item.style.background = '';
				item.style.color = '#334155';
			});
		});
	}

	function _searchOptions(txt) {
		_get_workstation_options(txt).then(results => {
			if (_destroyed) return;
			options = results || [];
			highlightIdx = -1;
			_renderDropdown();
		});
	}

	input.addEventListener('input', () => {
		clearTimeout(_searchTimeout);
		_searchTimeout = setTimeout(() => _searchOptions(input.value), 200);
	});

	input.addEventListener('focus', () => {
		_searchOptions(input.value);
	});

	input.addEventListener('blur', () => {
		setTimeout(() => {
			dropdown.style.display = 'none';
		}, 200);
	});

	input.addEventListener('keydown', (e) => {
		const filtered = options.filter(o => !selected.includes(o));
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			highlightIdx = highlightIdx < 0 ? 0 : Math.min(highlightIdx + 1, filtered.length - 1);
			_renderDropdown();
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			highlightIdx = highlightIdx <= 0 ? 0 : highlightIdx - 1;
			_renderDropdown();
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (filtered.length && highlightIdx >= 0 && highlightIdx < filtered.length) {
				const val = filtered[highlightIdx];
				if (!selected.includes(val)) {
					selected.push(val);
					_renderTags();
					_fireChange();
				}
				input.value = '';
				highlightIdx = 0;
				_searchOptions('');
			}
		} else if (e.key === 'Backspace' && !input.value && selected.length) {
			selected.pop();
			_renderTags();
			_fireChange();
		}
	});

	wrapper.addEventListener('click', () => input.focus());

	_renderTags();

	return {
		el: wrapper,
		getValues: () => selected.slice(),
		getCsv: () => selected.join(','),
		setValues: (vals) => {
			selected = vals.slice();
			_renderTags();
		},
		focus: () => input.focus(),
		destroy: () => {
			_destroyed = true;
			clearTimeout(_searchTimeout);
		}
	};
}

/**
 * Creates a reusable inline tag autocomplete widget for Shift Types.
 */
function _create_inline_shift_editor(initial_csv, onchange) {
	const wrapper = document.createElement('div');
	wrapper.style.cssText = _TAG_WRAPPER_STYLE;

	const tagsContainer = document.createElement('span');
	tagsContainer.style.cssText = 'display:contents;';
	wrapper.appendChild(tagsContainer);

	const input = document.createElement('input');
	input.type = 'text';
	input.placeholder = 'Type to add…';
	input.style.cssText = _TAG_INPUT_STYLE;
	input.setAttribute('autocomplete', 'off');
	wrapper.appendChild(input);

	const dropdown = document.createElement('div');
	dropdown.style.cssText = _DROPDOWN_STYLE;
	dropdown.style.display = 'none';
	wrapper.appendChild(dropdown);

	let selected = _parse_csv_list(initial_csv);
	let options = [];
	let highlightIdx = -1;
	let _searchTimeout = null;
	let _destroyed = false;

	function _renderTags() {
		tagsContainer.innerHTML = _render_machine_tags(selected);
		tagsContainer.querySelectorAll('.bpp-machine-tag-remove').forEach(btn => {
			btn.addEventListener('click', (e) => {
				e.stopPropagation();
				const val = btn.getAttribute('data-value');
				selected = selected.filter(v => v !== val);
				_renderTags();
				_fireChange();
			});
		});
		if (!selected.length) {
			input.placeholder = 'Type to add…';
		} else {
			input.placeholder = '';
		}
	}

	function _fireChange() {
		if (onchange) onchange(selected.join(','));
	}

	function _renderDropdown() {
		const filtered = options.filter(o => !selected.includes(o));
		if (!filtered.length || _destroyed) {
			dropdown.style.display = 'none';
			dropdown.innerHTML = '';
			return;
		}
		highlightIdx = Math.min(highlightIdx, filtered.length - 1);
		dropdown.innerHTML = filtered.map((o, i) => {
			const hl = i === highlightIdx ? _DROPDOWN_ITEM_HOVER : '';
			return `<div class="bpp-machine-dd-item" data-value="${frappe.utils.escape_html(o)}" style="${_DROPDOWN_ITEM_STYLE}${hl}">${frappe.utils.escape_html(o)}</div>`;
		}).join('');
		dropdown.style.display = 'block';
		dropdown.querySelectorAll('.bpp-machine-dd-item').forEach(item => {
			item.addEventListener('mousedown', (e) => {
				e.preventDefault();
				const val = item.getAttribute('data-value');
				if (val && !selected.includes(val)) {
					selected.push(val);
					_renderTags();
					_fireChange();
				}
				input.value = '';
				_searchOptions('');
				input.focus();
			});
			item.addEventListener('mouseenter', () => {
				item.style.background = '#EFF6FF';
				item.style.color = '#1E40AF';
			});
			item.addEventListener('mouseleave', () => {
				item.style.background = '';
				item.style.color = '#334155';
			});
		});
	}

	function _searchOptions(txt) {
		_get_shift_type_options(txt).then(results => {
			if (_destroyed) return;
			options = results || [];
			highlightIdx = -1;
			_renderDropdown();
		});
	}

	input.addEventListener('input', () => {
		clearTimeout(_searchTimeout);
		_searchTimeout = setTimeout(() => _searchOptions(input.value), 200);
	});

	input.addEventListener('focus', () => {
		_searchOptions(input.value);
	});

	input.addEventListener('blur', () => {
		setTimeout(() => {
			dropdown.style.display = 'none';
		}, 200);
	});

	input.addEventListener('keydown', (e) => {
		const filtered = options.filter(o => !selected.includes(o));
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			highlightIdx = highlightIdx < 0 ? 0 : Math.min(highlightIdx + 1, filtered.length - 1);
			_renderDropdown();
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			highlightIdx = highlightIdx <= 0 ? 0 : highlightIdx - 1;
			_renderDropdown();
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (filtered.length && highlightIdx >= 0 && highlightIdx < filtered.length) {
				const val = filtered[highlightIdx];
				if (!selected.includes(val)) {
					selected.push(val);
					_renderTags();
					_fireChange();
				}
				input.value = '';
				highlightIdx = 0;
				_searchOptions('');
			}
		} else if (e.key === 'Backspace' && !input.value && selected.length) {
			selected.pop();
			_renderTags();
			_fireChange();
		}
	});

	wrapper.addEventListener('click', () => input.focus());

	_renderTags();

	return {
		el: wrapper,
		getValues: () => selected.slice(),
		getCsv: () => selected.join(','),
		setValues: (vals) => {
			selected = vals.slice();
			_renderTags();
		},
		focus: () => input.focus(),
		destroy: () => {
			_destroyed = true;
			clearTimeout(_searchTimeout);
		}
	};
}

/**
 * AG Grid cell editor — inline tag autocomplete (no popup).
 */
class WorkstationPopupEditor {
	init(params) {
		this.params = params;
		this._tags = _create_inline_tag_editor(
			params.value || '',
			(csv) => this._onTagChange(csv)
		);
		this.eGui = this._tags.el;
		const popupWidth = Math.max(220, (params.column?.getActualWidth?.() || 340) - 16);
		this.eGui.style.boxSizing = 'border-box';
		this.eGui.style.width = `${popupWidth}px`;
		this.eGui.style.minWidth = `${popupWidth}px`;
		this.eGui.style.maxWidth = `${popupWidth}px`;
		this.eGui.style.marginLeft = '8px';
	}

	async _onTagChange(csv) {
		const frm = this.params.frm;
		const row_name = this.params.row_name;
		const row_type = this.params.row_type || 'sfg';
		const machine_count = _parse_csv_list(csv).length;
		let shift_count = 1;
		if (frm && row_name) {
			const row = _find_bpp_row(frm, row_name, row_type);
			shift_count = _shift_count_from_row(row);
		}
		const spm = Number(this.params.base_batchsize || 0) * machine_count * shift_count;
		if (frm && row_name) {
			const row = _find_bpp_row(frm, row_name, row_type);
			if (row) {
				row.custom_workstations_csv = csv;
				row.machine_count = machine_count;
				row.spm = spm;
				_mark_bom_form_dirty(frm);
				if (row.doctype && row.name) {
					await frappe.model.set_value(row.doctype, row.name, 'custom_workstations_csv', csv);
					await frappe.model.set_value(row.doctype, row.name, 'spm', spm);
					await frappe.model.set_value(row.doctype, row.name, 'machine_count', machine_count);
				}
			}
		}
		_sync_parallel_schedule_override(frm, row_name, row_type, {
			custom_workstations_csv: csv,
			machine_count,
			spm
		});
		if (this.params.data) {
			this.params.data.custom_workstations_csv = csv;
			this.params.data.machine_count = machine_count;
			this.params.data.spm = spm;
		}
		if (this.params.api) {
			this.params.api.refreshCells({ force: true });
		}
	}

	getGui() {
		return this.eGui;
	}

	afterGuiAttached() {
		this._tags.focus();
	}

	getValue() {
		return this._tags.getCsv();
	}

	isPopup() {
		return true;
	}

	getPopupPosition() {
		return 'under';
	}

	destroy() {
		if (this._tags) this._tags.destroy();
	}
}

/**
 * AG Grid cell editor — Shift Type multi-select (popup).
 */
class ShiftPopupEditor {
	init(params) {
		this.params = params;
		this._tags = _create_inline_shift_editor(
			params.value || '',
			(csv) => this._onTagChange(csv)
		);
		this.eGui = this._tags.el;
		const popupWidth = Math.max(220, (params.column?.getActualWidth?.() || 240) - 16);
		this.eGui.style.boxSizing = 'border-box';
		this.eGui.style.width = `${popupWidth}px`;
		this.eGui.style.minWidth = `${popupWidth}px`;
		this.eGui.style.maxWidth = `${popupWidth}px`;
		this.eGui.style.marginLeft = '8px';
	}

	async _onTagChange(csv) {
		const frm = this.params.frm;
		const row_name = this.params.row_name;
		const row_type = this.params.row_type || 'sfg';
		let override_spm = undefined;
		if (frm && row_name) {
			const row = _find_bpp_row(frm, row_name, row_type);
			if (row) {
				row.custom_shift_types_csv = csv;

				// Read batchsize and machine_count from params.data if possible, since
				// un-rendered or child doc rows might not have these transient attributes.
				const gridData = this.params.data || {};
				const machine_count = Number(gridData.machine_count || row.machine_count || _parse_csv_list(row.custom_workstations_csv).length || 0);
				const batchsize = Number(gridData.batchsize || row.batchsize || 0);

				const shift_count = _shift_count_from_row({ custom_shift_types_csv: csv });
				const spm = batchsize * machine_count * shift_count;

				if (spm > 0) {
					row.spm = spm;
					override_spm = spm;
				}
				_mark_form_dirty(frm);
				if (row.doctype && row.name) {
					await frappe.model.set_value(row.doctype, row.name, 'custom_shift_types_csv', csv);
					if (spm > 0) {
						await frappe.model.set_value(row.doctype, row.name, 'spm', spm);
					}
				}
			}
		}

		if (this.params.data) {
			this.params.data.custom_shift_types_csv = csv;
			this.params.data.spm = this.params.data.batchsize
				? (Number(this.params.data.batchsize || 0)
					* Number(this.params.data.machine_count || _parse_csv_list(this.params.data.custom_workstations_csv).length || 0)
					* _shift_count_from_row({ custom_shift_types_csv: csv }))
				: this.params.data.spm;
			if (override_spm === undefined) override_spm = this.params.data.spm;
		}

		const overrides = { custom_shift_types_csv: csv };
		if (override_spm !== undefined) overrides.spm = override_spm;
		_sync_parallel_schedule_override(frm, row_name, row_type, overrides);

		if (this.params.api) {
			this.params.api.refreshCells({ force: true });
		}
	}

	getGui() { return this.eGui; }
	afterGuiAttached() { this._tags.focus(); }
	getValue() { return this._tags.getCsv(); }
	isPopup() { return true; }
	getPopupPosition() { return 'under'; }
	destroy() { if (this._tags) this._tags.destroy(); }
}

function _get_bom_options(item_code, current_bom) {
	const options = (_bom_options_cache[item_code] || []).slice();
	if (current_bom && !options.includes(current_bom)) {
		options.unshift(current_bom);
	}
	return options;
}

function _render_bom_select_options(item_code, selected_bom) {
	const options = _get_bom_options(item_code, selected_bom);
	return options.map(bom_no => {
		const selected = bom_no === selected_bom ? ' selected' : '';
		return `<option value="${frappe.utils.escape_html(bom_no)}"${selected}>${frappe.utils.escape_html(bom_no)}</option>`;
	}).join('');
}

function _render_tool_select_options(tools, selected_tool) {
	const rows = Array.isArray(tools) ? tools : [];
	if (!rows.length) {
		return `<option value="">${selected_tool ? frappe.utils.escape_html(selected_tool) : 'No Tool'}</option>`;
	}
	return rows.map(row => {
		const tool = row?.tool || '';
		const selected = tool === selected_tool ? ' selected' : '';
		return `<option value="${frappe.utils.escape_html(tool)}"${selected}>${frappe.utils.escape_html(tool || 'No Tool')}</option>`;
	}).join('');
}

function _bind_fg_bom_selects(frm, wrapper) {
	$(wrapper).find('.bpp-fg-bom-select').off('change').on('change', function () {
		const row_name = $(this).data('row-name');
		const new_bom = $(this).val();
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row || !new_bom || row.bom_no === new_bom) return;

		frappe.model.set_value(row.doctype, row.name, 'bom_no', new_bom).then(() => {
			_handle_bom_change(frm, row.name, new_bom, 'fg', { wrapper });
		});
	});
}

function _bind_fg_tool_selects(frm, wrapper) {
	$(wrapper).find('.bpp-fg-tool-select').each(function () {
		const row_name = $(this).data('row-name');
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row?.bom_no) return;
		get_bom_details(row.bom_no, row.custom_workstations_csv || '', row.tool || '').then(details => {
			this.innerHTML = _render_tool_select_options(details?.tools || [], details?.tool || row.tool || '');
			this.value = details?.tool || row.tool || '';
			this.disabled = !(details?.tools || []).length;
			this.title = details?.tool_load_qty
				? `Load Qty: ${details.tool_load_qty}${details?.pm_days ? ` | PM Days: ${details.pm_days}` : ''}`
				: '';
			if (!row.tool && details?.tool) {
				row.tool = details.tool;
				row.tool_load_qty = details.tool_load_qty || 0;
				row.pm_days = details.pm_days || 0;
			}
		});
	});

	$(wrapper).find('.bpp-fg-tool-select').off('change').on('change', function () {
		const row_name = $(this).data('row-name');
		const new_tool = $(this).val();
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row || row.tool === new_tool) return;

		frappe.model.set_value(row.doctype, row.name, 'tool', new_tool).then(() => {
			_handle_tool_change(frm, row.name, 'fg', new_tool, { wrapper });
		}).catch(() => {
			_handle_tool_change(frm, row.name, 'fg', new_tool, { wrapper });
		});
	});
}

/** Shows CSV display for FG machine cells, opens inline tag editor on click */
function _bind_fg_machine_selects(frm, wrapper) {
	$(wrapper).find('.bpp-fg-machine-inline').each(function () {
		const host = this;
		const row_name = $(host).data('row-name');
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row) return;

		// Fetch BOM defaults and render CSV display
		get_bom_details(row.bom_no, row.custom_workstations_csv || '', row.tool || '').then(details => {
			const initial_csv = row.custom_workstations_csv || details.selected_workstations_csv || details.workstations_csv || '';
			if (!row.custom_workstations_csv && initial_csv) {
				row.custom_workstations_csv = initial_csv;
				row.machine_count = details.machine_count || _parse_csv_list(initial_csv).length;
				row.spm = details.spm || _effective_spm_value({
					batchsize: details.batchsize || 0,
					custom_workstations_csv: initial_csv,
					machine_count: details.machine_count || 0
				});
			}

			// Show comma-separated text by default
			_render_fg_machine_display(host, initial_csv);
		});
	});

	// Click to open inline tag editor
	$(wrapper).find('.bpp-fg-machine-inline').off('click.bpp_machine').on('click.bpp_machine', function (e) {
		const host = this;
		if (host._editing) return;
		const row_name = $(host).data('row-name');
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row) return;

		host._editing = true;
		host.innerHTML = '';
		const editor = _create_inline_tag_editor(row.custom_workstations_csv || '', (csv) => {
			row.custom_workstations_csv = csv;
			_render_fg_machine_display(host, csv);
			frappe.model.set_value(row.doctype, row.name, 'custom_workstations_csv', csv).then(() => {
				_handle_workstation_change(frm, row.name, 'fg', csv, { wrapper });
			});
		});
		host.appendChild(editor.el);
		host._editor = editor;
		editor.focus();

		// Close editor when clicking outside
		function _closeOnOutsideClick(ev) {
			if (!host.contains(ev.target)) {
				document.removeEventListener('mousedown', _closeOnOutsideClick, true);
				const csv = editor.getCsv();
				editor.destroy();
				host._editing = false;
				host._editor = null;
				_render_fg_machine_display(host, csv);
			}
		}
		setTimeout(() => document.addEventListener('mousedown', _closeOnOutsideClick, true), 50);
	});
}

/** Shows CSV display for FG shift cells, opens inline tag editor on click */
function _bind_fg_shift_selects(frm, wrapper) {
	$(wrapper).find('.bpp-fg-shift-inline').each(function () {
		const host = this;
		const row_name = $(host).data('row-name');
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row) return;
		const initial_csv = row.custom_shift_types_csv || '';
		_render_fg_shift_display(host, initial_csv);
	});

	$(wrapper).find('.bpp-fg-shift-inline').off('click.bpp_shift').on('click.bpp_shift', function () {
		const host = this;
		if (host._editing) return;
		const row_name = $(host).data('row-name');
		const row = _find_bpp_row(frm, row_name, 'fg');
		if (!row) return;

		host._editing = true;
		host.innerHTML = '';
		const editor = _create_inline_shift_editor(row.custom_shift_types_csv || '', (csv) => {
			row.custom_shift_types_csv = csv;
			const machine_count = Number(row.machine_count || _parse_csv_list(row.custom_workstations_csv).length || 0);
			const batchsize = Number(row.batchsize || 0);
			const shift_count = _shift_count_from_row({ custom_shift_types_csv: csv });
			const spm = batchsize * machine_count * shift_count;
			row.spm = spm;
			_render_fg_shift_display(host, csv);
			frappe.model.set_value(row.doctype, row.name, 'custom_shift_types_csv', csv);
			frappe.model.set_value(row.doctype, row.name, 'spm', spm);
			_sync_parallel_schedule_override(frm, row.name, 'fg', { custom_shift_types_csv: csv, spm: spm });
			_mark_form_dirty(frm);
		});
		host.appendChild(editor.el);
		host._editor = editor;
		editor.focus();

		function _closeOnOutsideClick(ev) {
			if (!host.contains(ev.target)) {
				document.removeEventListener('mousedown', _closeOnOutsideClick, true);
				const csv = editor.getCsv();
				editor.destroy();
				host._editing = false;
				host._editor = null;
				_render_fg_shift_display(host, csv);
			}
		}
		setTimeout(() => document.addEventListener('mousedown', _closeOnOutsideClick, true), 50);
	});
}

/** Renders comma-separated shift text in an FG cell */
function _render_fg_shift_display(host, csv) {
	const values = _parse_csv_list(csv);
	const label = values.length ? values.join(', ') : 'Select';
	host.innerHTML = `<div style="border:1px solid #CBD5E1;background:#fff;border-radius:4px;padding:6px 8px;font-size:12px;color:#334155;width:100%;text-align:left;box-sizing:border-box;cursor:pointer;" title="${frappe.utils.escape_html(label)}">
		${frappe.utils.escape_html(label)}
	</div>`;
}

/** Renders comma-separated machine text in an FG cell */
function _render_fg_machine_display(host, csv) {
	const values = _parse_csv_list(csv);
	const label = values.length ? values.join(', ') : 'Select';
	host.innerHTML = `<div style="border:1px solid #CBD5E1;background:#fff;border-radius:4px;padding:6px 8px;font-size:12px;color:#334155;width:100%;text-align:left;box-sizing:border-box;cursor:pointer;" title="${frappe.utils.escape_html(label)}">
		${frappe.utils.escape_html(label)}
	</div>`;
}

function _clear_parallel_schedule(frm) {
	if (frm.doc.custom_batch_schedule) {
		frm.set_value('custom_batch_schedule', '');
	}
	frm.dirty();
}

function _on_par_bom_changed(frm, params, par_data) {
	if (!params.data?._is_group || params.oldValue === params.newValue) return;

	const row_table = params.data?._row_table || 'sfg';
	const target_row = _find_bpp_row(frm, params.data._row_name, row_table);
	if (!target_row) return;
	const fieldname = params.colDef.field;

	if (fieldname === 'bom_no' || fieldname === 'custom_workstations_csv' || fieldname === 'tool') {
		_mark_bom_form_dirty(frm);
		target_row[fieldname] = params.newValue;
		params.data[fieldname] = params.newValue;
	}

	if (fieldname === 'bom_no') {
		frappe.model.set_value(target_row.doctype, target_row.name, 'bom_no', params.newValue).then(() => {
			_handle_bom_change(frm, target_row.name, params.newValue, row_table, { params, par_data });
		}).catch(() => {
			_handle_bom_change(frm, target_row.name, params.newValue, row_table, { params, par_data });
		});
		return;
	}

	if (fieldname === 'tool') {
		frappe.model.set_value(target_row.doctype, target_row.name, 'tool', params.newValue).then(() => {
			_handle_tool_change(frm, target_row.name, row_table, params.newValue, { params, par_data });
		}).catch(() => {
			_handle_tool_change(frm, target_row.name, row_table, params.newValue, { params, par_data });
		});
		return;
	}

	if (fieldname === 'custom_workstations_csv') {
		frappe.model.set_value(target_row.doctype, target_row.name, 'custom_workstations_csv', params.newValue).then(() => {
			_handle_workstation_change(frm, target_row.name, row_table, params.newValue, { params, par_data });
		}).catch(() => {
			_handle_workstation_change(frm, target_row.name, row_table, params.newValue, { params, par_data });
		});
	}

	if (fieldname === 'type') {
		if (row_table === 'fg') {
			frappe.model.set_value(target_row.doctype, target_row.name, 'manufacturing_type', params.newValue).then(() => {
				_sync_parallel_schedule_override(frm, target_row.name, 'fg', { manufacturing_type: params.newValue });

				if (['Subcontract', 'In House - Vendor'].includes(params.newValue)) {
					frappe.call({
						method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_default_supplier_for_item',
						args: { item_code: target_row.item_code, company: frm.doc.company },
						callback: function (r) {
							if (r.message && r.message !== target_row.custom_supplier) {
								frappe.model.set_value(target_row.doctype, target_row.name, 'custom_supplier', r.message).then(() => {
									params.node.setDataValue('supplier', r.message);
									_sync_parallel_schedule_override(frm, target_row.name, 'fg', { custom_supplier: r.message });
								});
							}
						}
					});
				} else if (params.newValue === 'In House') {
					frappe.model.set_value(target_row.doctype, target_row.name, 'custom_supplier', '').then(() => {
						params.node.setDataValue('supplier', '');
						_sync_parallel_schedule_override(frm, target_row.name, 'fg', { custom_supplier: '' });
					});
				}
			});
			return;
		}

		frappe.model.set_value(target_row.doctype, target_row.name, 'type_of_manufacturing', params.newValue).then(() => {
			_sync_parallel_schedule_override(frm, target_row.name, 'sfg', { type_of_manufacturing: params.newValue });

			if (['Subcontract', 'In House - Vendor'].includes(params.newValue)) {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_default_supplier_for_item',
					args: {
						item_code: target_row.production_item || target_row.item_code,
						company: frm.doc.company
					},
					callback: function (r) {
						if (r.message && r.message !== target_row.supplier) {
							frappe.model.set_value(target_row.doctype, target_row.name, 'supplier', r.message).then(() => {
								params.node.setDataValue('supplier', r.message);
								_sync_parallel_schedule_override(frm, target_row.name, 'sfg', { supplier: r.message });
							});
						}
					}
				});
			} else if (params.newValue === 'In House') {
				frappe.model.set_value(target_row.doctype, target_row.name, 'supplier', '').then(() => {
					params.node.setDataValue('supplier', '');
					_sync_parallel_schedule_override(frm, target_row.name, 'sfg', { supplier: '' });
				});
			}
		});
	}
}

function get_bom_details(bom_no, selected_workstations_csv = null, selected_tool = null) {
	return new Promise(resolve => {
		if (!bom_no) {
			resolve({
				bom_no: '',
				batchsize: 0,
				workstations: [],
				workstations_csv: '',
				selected_workstations_csv: '',
				machine_count: 0,
				spm: 0,
				tool: '',
				tool_load_qty: 0,
				pm_days: 0,
				tools: []
			});
			return;
		}
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_bom_spm_details',
			args: { bom_no, selected_workstations_csv, selected_tool },
			callback: function (r) {
				resolve(r.message || {});
			}
		});
	});
}

function get_bom_spm(bom_no, selected_workstations_csv = null) {
	return get_bom_details(bom_no, selected_workstations_csv).then(details => details?.spm || 0);
}

function _recalculate_parallel_schedule(frm) {
	const html_field = frm.fields_dict.production_items_html;
	if (!html_field || !html_field.$wrapper) {
		_bom_recalc_inflight = false;
		return;
	}

	const so_map = _build_so_map(frm);
	frappe.show_alert({ message: __('Recalculating parallel schedule…'), indicator: 'blue' });
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.calculate_parallel_batch_schedule',
		args: { docname: frm.doc.name },
		callback(r) {
			if (!r.message) {
				_bom_recalc_inflight = false;
				return;
			}
			const json_str = JSON.stringify(r.message);
			frm.set_value('custom_batch_schedule', json_str);
			frappe.show_alert({ message: __('Parallel schedule updated'), indicator: 'green' });
			_render_all_grids(frm, so_map, 'Parallel', html_field.$wrapper, r.message);
			_bom_recalc_inflight = false;
		}
	});
}

function _run_bom_change_recalculation(frm) {
	const mode = frm.doc.custom_planning_mode || 'Sequential';
	const scope = frm._bom_change_scope || 'existing';
	frappe.show_alert({ message: __('Updating BOM calculations…'), indicator: 'blue' });
	frappe.call({
		method: scope === 'fg'
			? 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.generate_production_plan_items'
			: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.recalculate_existing_schedule',
		args: { docname: frm.doc.name, planning_mode: mode },
		callback(r) {
			if (!r.message) {
				_bom_recalc_inflight = false;
				return;
			}
			frm._bom_changed = false;
			frm._bom_change_scope = null;
			frm.reload_doc().then(() => {
				if (mode === 'Parallel') {
					const html_field = frm.fields_dict.production_items_html;
					let schedule = null;
					try {
						schedule = frm.doc.custom_batch_schedule ? JSON.parse(frm.doc.custom_batch_schedule) : null;
					} catch (e) { }
					frappe.show_alert({ message: __('Parallel schedule updated'), indicator: 'green' });
					if (html_field && html_field.$wrapper) {
						_render_all_grids(frm, _build_so_map(frm), 'Parallel', html_field.$wrapper, schedule);
					}
				} else {
					frappe.show_alert({ message: __('Sequential schedule updated'), indicator: 'green' });
				}
				_bom_recalc_inflight = false;
			});
		}
	});
}

function _mark_bom_form_dirty(frm) {
	frm._bom_changed = true;
	frm.doc.__unsaved = 1;
	frm.dirty();
	if (typeof frm.refresh_header === 'function') {
		frm.refresh_header();
	}
}

function _mark_form_dirty(frm) {
	// Marks the form dirty without triggering BOM recalculation on save.
	frm.doc.__unsaved = 1;
	frm.dirty();
	if (typeof frm.refresh_header === 'function') {
		frm.refresh_header();
	}
}

function _handle_bom_change(frm, row_name, bom_no, row_type, context = {}) {
	_mark_bom_form_dirty(frm);

	if (row_type === 'fg') {
		frm._bom_change_scope = 'fg';
	} else if (frm._bom_change_scope !== 'fg') {
		frm._bom_change_scope = 'existing';
	}

	const row = _find_bpp_row(frm, row_name, row_type);
	if (row) {
		row.bom_no = bom_no;
		row.tool = '';
	}

	get_bom_details(bom_no).then(details => {
		const selected_csv = details?.selected_workstations_csv || details?.workstations_csv || '';
		const updates = [];
		if (row && (row.custom_workstations_csv || '') !== selected_csv) {
			updates.push(frappe.model.set_value(row.doctype, row.name, 'custom_workstations_csv', selected_csv));
		}
		if (row && (row.tool || '') !== (details?.tool || '')) {
			updates.push(frappe.model.set_value(row.doctype, row.name, 'tool', details?.tool || ''));
		}
		if (row) {
			updates.push(frappe.model.set_value(row.doctype, row.name, 'tool_load_qty', details?.tool_load_qty || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'pm_days', details?.pm_days || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'spm', details?.spm || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'machine_count', details?.machine_count || 0));
		}

		Promise.all(updates).then(() => {
			if (row_type === 'fg') {
				_sync_fg_bom_selection(frm, row_name, bom_no, details?.spm || 0);
			}
			_sync_parallel_schedule_override(frm, row_name, row_type, {
				bom_no,
				tool: details?.tool || '',
				custom_workstations_csv: selected_csv,
				machine_count: details?.machine_count || 0,
				spm: details?.spm || 0,
				batchsize: details?.batchsize || 0,
				tool_load_qty: details?.tool_load_qty || 0,
				pm_days: details?.pm_days || 0,
				tools: details?.tools || []
			});
			_apply_bom_details_to_context(row_name, details, context);
			if (context.wrapper) {
				_bind_fg_tool_selects(frm, context.wrapper);
				_bind_fg_machine_selects(frm, context.wrapper);
			}
		});
	});
}

function _handle_workstation_change(frm, row_name, row_type, selected_csv, context = {}) {
	_mark_bom_form_dirty(frm);

	// Machine changes only affect capacity/SPM, never the BOM tree structure.
	// Force existing-row recalculation so a prior FG BOM change scope doesn't
	// accidentally regenerate rows and restore old workstation CSV.
	frm._bom_change_scope = 'existing';

	const row = _find_bpp_row(frm, row_name, row_type);
	if (row) {
		row.custom_workstations_csv = selected_csv;
	}
	const bom_no = row?.bom_no;
	if (!bom_no) return;

	get_bom_details(bom_no, selected_csv, row?.tool || '').then(details => {
		const updates = [];
		if (row) {
			updates.push(frappe.model.set_value(row.doctype, row.name, 'tool_load_qty', details?.tool_load_qty || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'pm_days', details?.pm_days || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'spm', details?.spm || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'machine_count', details?.machine_count || 0));
		}
		Promise.all(updates).then(() => {
			if (row_type === 'fg') {
				_sync_fg_bom_selection(frm, row_name, bom_no, details?.spm || 0);
			}
			_sync_parallel_schedule_override(frm, row_name, row_type, {
				tool: details?.tool || row?.tool || '',
				custom_workstations_csv: details?.selected_workstations_csv || details?.workstations_csv || '',
				machine_count: details?.machine_count || 0,
				spm: details?.spm || 0,
				batchsize: details?.batchsize || 0,
				tool_load_qty: details?.tool_load_qty || 0,
				pm_days: details?.pm_days || 0,
				tools: details?.tools || []
			});
			_apply_bom_details_to_context(row_name, details, context);
		});
	});
}

function _handle_tool_change(frm, row_name, row_type, selected_tool, context = {}) {
	_mark_bom_form_dirty(frm);
	frm._bom_change_scope = 'existing';

	const row = _find_bpp_row(frm, row_name, row_type);
	if (row) {
		row.tool = selected_tool;
	}
	const bom_no = row?.bom_no;
	if (!bom_no) return;

	get_bom_details(bom_no, row?.custom_workstations_csv || '', selected_tool).then(details => {
		const updates = [];
		if (row) {
			updates.push(frappe.model.set_value(row.doctype, row.name, 'tool', details?.tool || selected_tool || ''));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'tool_load_qty', details?.tool_load_qty || 0));
			updates.push(frappe.model.set_value(row.doctype, row.name, 'pm_days', details?.pm_days || 0));
		}
		Promise.all(updates).then(() => {
			_sync_parallel_schedule_override(frm, row_name, row_type, {
				tool: details?.tool || selected_tool || '',
				tool_load_qty: details?.tool_load_qty || 0,
				pm_days: details?.pm_days || 0,
				tools: details?.tools || []
			});
			_apply_bom_details_to_context(row_name, details, context);
			if (context.wrapper) {
				_bind_fg_tool_selects(frm, context.wrapper);
			}
		});
	});
}

function _apply_bom_details_to_context(row_name, details, context = {}) {
	const spm = details?.spm || 0;
	const batchsize = details?.batchsize || 0;
	const selected_csv = details?.selected_workstations_csv || details?.workstations_csv || '';
	const machine_count = details?.machine_count || 0;
	const tool = details?.tool || '';
	const tool_load_qty = details?.tool_load_qty || 0;
	const pm_days = details?.pm_days || 0;
	const tools = details?.tools || [];

	if (context.params?.data) {
		context.params.data.batchsize = batchsize;
		context.params.data.spm = spm;
		context.params.data.custom_workstations_csv = selected_csv;
		context.params.data.machine_count = machine_count;
		context.params.data.tool = tool;
		context.params.data.tool_load_qty = tool_load_qty;
		context.params.data.pm_days = pm_days;
		context.params.data.tools = tools;
		if (context.par_data?.sfg_chain) {
			const chain_row = context.par_data.sfg_chain.find(item => item.row_name === row_name);
			if (chain_row) {
				chain_row.batchsize = batchsize;
				chain_row.spm = spm;
				chain_row.custom_workstations_csv = selected_csv;
				chain_row.machine_count = machine_count;
				chain_row.tool = tool;
				chain_row.tool_load_qty = tool_load_qty;
				chain_row.pm_days = pm_days;
				chain_row.tools = tools;
			}
		}
		context.params.api.refreshCells({ force: true });
	}

	if (!context.params && context.grid_api) {
		context.grid_api.forEachNode(node => {
			const match = node.data?._row_name === row_name || node.data?.name === row_name;
			if (!match) return;
			node.data.batchsize = batchsize;
			node.data.spm = spm;
			node.data.custom_workstations_csv = selected_csv;
			node.data.machine_count = machine_count;
			node.data.tool = tool;
			node.data.tool_load_qty = tool_load_qty;
			node.data.pm_days = pm_days;
			node.data.tools = tools;
		});
		context.grid_api.refreshCells({ force: true });
	}

	if (context.wrapper) {
		const toolSelect = $(context.wrapper).find(`.bpp-fg-tool-select[data-row-name="${row_name}"]`).get(0);
		if (toolSelect) {
			toolSelect.innerHTML = _render_tool_select_options(tools, tool);
			toolSelect.value = tool || '';
			toolSelect.disabled = !tools.length;
			toolSelect.title = tool_load_qty
				? `Load Qty: ${tool_load_qty}${pm_days ? ` | PM Days: ${pm_days}` : ''}`
				: '';
		}
		const inlineHost = $(context.wrapper).find(`.bpp-fg-machine-inline[data-row-name="${row_name}"]`).get(0);
		if (inlineHost) {
			if (inlineHost._editor) {
				inlineHost._editor.setValues(_parse_csv_list(selected_csv));
			} else {
				_render_fg_machine_display(inlineHost, selected_csv);
			}
		}
	}
}

function _sync_fg_bom_selection(frm, fg_row_name, bom_no, spm = 0) {
	const fg_row = _find_bpp_row(frm, fg_row_name, 'fg');
	if (!fg_row || !fg_row.sales_order_item) return;

	const selection_row = (frm.doc.bom_selections || []).find(item => item.sales_order_item === fg_row.sales_order_item);
	if (!selection_row) return;

	frappe.model.set_value(selection_row.doctype, selection_row.name, 'bom_no', bom_no);
	frappe.model.set_value(selection_row.doctype, selection_row.name, 'spm', spm || 0);
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
	label.setAttribute('data-bpp-section', 'mr');
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
		{
			headerName: 'Item Code', field: 'item_code', width: 130,
			cellRenderer: p => `<strong>${p.value || ''}</strong>`
		},
		{
			headerName: 'Item Name', field: 'item_name', width: 160,
			cellRenderer: p => `<span style="color:#64748b;font-size:11px;">${p.data ? (p.data.item_name || p.data.description || '') : ''}</span>`
		},
		{
			headerName: 'Qty', field: _par ? 'qty' : 'quantity', width: 90, type: 'numericColumn',
			valueFormatter: p => p.value ? Number(p.value).toLocaleString('en-IN') : ''
		},
		{ headerName: 'UOM', field: 'uom', width: 65 },
		...(_par ? [
			{ headerName: 'GRN Days', field: 'grn_days', width: 80, type: 'numericColumn' },
			{ headerName: 'Lead Days', field: 'lead_days', width: 85, type: 'numericColumn' },
		] : []),
		{
			headerName: 'Order By', field: _par ? 'start_date' : 'custom_start_date',
			width: 110, editable: true,
			cellStyle: { color: '#0F5132', fontWeight: '600' },
			valueFormatter: p => _format_bpp_date(p.value, '')
		},
		{
			headerName: 'Receive By', field: _par ? 'end_date' : 'schedule_date',
			width: 110, editable: true,
			cellStyle: { color: '#842029', fontWeight: '600' },
			valueFormatter: p => _format_bpp_date(p.value, '')
		},
		{ headerName: 'Supplier', field: _par ? 'supplier' : 'custom_supplier', width: 150 },
	];

	agGrid.createGrid(mr_el, {
		columnDefs: mr_cols,
		rowData: mr_items,
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

function _format_bpp_date(value, empty_value = '—', show_time = false) {
	if (!value) return empty_value;

	const str = String(value);
	const date_part = str.split(' ')[0];
	const parts = date_part.split('-');
	if (parts.length !== 3) return date_part;

	const [year, month, day] = parts;
	const date_str = `${day}-${month}-${year}`;

	if (show_time) {
		const time_raw = str.split(' ')[1] || '';
		if (time_raw) {
			const [h, m] = time_raw.split(':');
			return `${date_str} ${h}:${m}`;
		}
	}
	return date_str;
}

function add_sales_order_filters(frm) {
	const grid = frm.fields_dict['sales_orders'].grid;
	const $wrapper = grid.wrapper;

	// Attach filter input handler once
	$wrapper.off('input.sofilter').on('input.sofilter', '.so-filter', function () {
		_apply_so_filters(frm);
	});

	// (Re-)render the filter row after grid header is in DOM
	setTimeout(() => {
		$wrapper.find('.so-filter-row').remove();

		const $heading_row = $wrapper.find('.grid-heading-row .grid-row .data-row');
		if (!$heading_row.length) return;

		const $filter_row = $('<div class="so-filter-row" style="display:flex;background:#f5f7fa;border-bottom:1px solid #d1d8dd;"></div>');

		const label_map = {
			sales_order: 'Sales Order…',
			customer: 'Customer…',
			delivery_date: 'Date…',
			grand_total: 'Amount…',
		};

		$heading_row.children().each(function () {
			const $th = $(this);
			const fieldname = $th.data('fieldname');
			const w = $th.outerWidth(true);

			const $td = $('<div></div>').css({
				width: w, minWidth: w, maxWidth: w,
				padding: '3px 4px', boxSizing: 'border-box',
			});

			if (label_map[fieldname]) {
				$td.append(
					`<input type="text" class="so-filter form-control form-control-sm"
					 data-col="${fieldname}" placeholder="${label_map[fieldname]}"
					 style="height:22px;font-size:11px;padding:1px 5px;width:100%;">`
				);
			}
			$filter_row.append($td);
		});

		$heading_row.closest('.grid-heading-row').after($filter_row);
	}, 150);
}

function _apply_so_filters(frm) {
	const grid = frm.fields_dict['sales_orders'].grid;
	const $wrapper = grid.wrapper;
	const doctype = grid.doctype;

	const filters = {};
	$wrapper.find('.so-filter').each(function () {
		const val = $(this).val().trim().toLowerCase();
		if (val) filters[$(this).data('col')] = val;
	});

	$wrapper.find('.grid-body .rows .grid-row').each(function () {
		const row = locals[doctype]?.[$(this).attr('data-name')];
		if (!row) return;
		let show = true;
		for (const [col, val] of Object.entries(filters)) {
			if (!String(row[col] || '').toLowerCase().includes(val)) {
				show = false; break;
			}
		}
		$(this).toggle(show);
	});
}


