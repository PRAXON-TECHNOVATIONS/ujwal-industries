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

		frappe.confirm(
			__('Start Pre Production Planning for {0} selected Sales Order(s)?<br><br>This will generate:<br>• Finished Goods (FG)<br>• Sub Assembly Items (SFG)<br>• Raw Materials (RM)', [selected_count]),
			function() {
				frappe.show_alert({
					message: __('Generating production plan...'),
					indicator: 'blue'
				});

				frappe.call({
					method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.generate_production_plan_items',
					args: {
						docname: frm.doc.name
					},
					callback: function(r) {
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
		);
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


function setup_production_tabs(frm) {
	/**
	 * Create beautiful sales order-wise tabs showing FG, SFG, and RM items
	 */

	// Get unique sales orders from po_items
	const sales_orders_map = {};

	// Build sales order map with all items
	(frm.doc.po_items || []).forEach(function(item) {
		if (!sales_orders_map[item.sales_order]) {
			sales_orders_map[item.sales_order] = {
				sales_order: item.sales_order,
				fg_items: [],
				sfg_items: [],
				rm_items: []
			};
		}
		sales_orders_map[item.sales_order].fg_items.push(item);
	});

	(frm.doc.sub_assembly_items || []).forEach(function(item) {
		if (sales_orders_map[item.sales_order]) {
			sales_orders_map[item.sales_order].sfg_items.push(item);
		}
	});

	(frm.doc.mr_items || []).forEach(function(item) {
		if (sales_orders_map[item.sales_order]) {
			sales_orders_map[item.sales_order].rm_items.push(item);
		}
	});

	const sales_orders = Object.values(sales_orders_map);

	if (!sales_orders || sales_orders.length === 0) {
		return;
	}

	// Get the HTML field wrapper
	const html_field = frm.fields_dict.production_items_html;
	if (!html_field || !html_field.$wrapper) {
		return;
	}

	// Clear existing content
	html_field.$wrapper.empty();

	// Create tabs container
	const tabs_html = `
		<div class="production-tabs-container" style="margin-top: 15px;">
			<ul class="nav nav-tabs" id="productionTabs" role="tablist"></ul>
			<div class="tab-content" id="productionTabContent" style="margin-top: 20px;"></div>
		</div>
	`;

	html_field.$wrapper.html(tabs_html);

	const tabs_ul = html_field.$wrapper.find('#productionTabs');
	const tabs_content = html_field.$wrapper.find('#productionTabContent');

	// Create tab for each sales order
	sales_orders.forEach(function(so_data, index) {
		const so_name = so_data.sales_order;
		const is_active = index === 0;

		// Get SO details from sales_orders table
		const so_row = (frm.doc.sales_orders || []).find(row => row.sales_order === so_name);
		const customer = so_row ? so_row.customer : '';
		const delivery_date = so_row ? frappe.format(so_row.delivery_date, {fieldtype: 'Date'}) : '';

		// Create tab header with click handler
		const tab_button = $(`
			<li class="nav-item" role="presentation">
				<a class="nav-link ${is_active ? 'active' : ''}"
					id="so-tab-${index}"
					data-tab-index="${index}"
					role="tab"
					style="padding: 10px 20px; font-size: 14px; cursor: pointer;">
					<strong>${so_name}</strong><br>
					<small class="text-muted" style="font-size: 11px;">${customer}</small>
				</a>
			</li>
		`);

		// Add click handler
		tab_button.find('a').on('click', function(e) {
			e.preventDefault();
			const tab_index = $(this).data('tab-index');

			// Remove active class from all tabs and content
			tabs_ul.find('.nav-link').removeClass('active');
			tabs_content.find('.tab-pane').removeClass('show active');

			// Add active class to clicked tab and its content
			$(this).addClass('active');
			tabs_content.find('#so-content-' + tab_index).addClass('show active');
		});

		tabs_ul.append(tab_button);

		// Create tab content
		const tab_content = `
			<div class="tab-pane fade ${is_active ? 'show active' : ''}"
				id="so-content-${index}"
				role="tabpanel">

				<!-- SO Header -->
				<div class="card mb-3" style="border: 1px solid #d1d8dd;">
					<div class="card-body" style="padding: 15px;">
						<div class="row">
							<div class="col-md-4">
								<strong>Sales Order:</strong> ${so_name}
							</div>
							<div class="col-md-4">
								<strong>Customer:</strong> ${customer}
							</div>
							<div class="col-md-4">
								<strong>Delivery Date:</strong> ${delivery_date}
							</div>
						</div>
					</div>
				</div>

				<!-- FG Items -->
				<div class="mb-4">
					<h5 style="margin-bottom: 15px; color: #36414C; border-bottom: 2px solid #2490ef; padding-bottom: 8px;">
						<i class="fa fa-cube"></i> Finished Goods (${so_data.fg_items.length})
					</h5>
					${render_fg_table(so_data.fg_items)}
				</div>

				<!-- SFG Items -->
				<div class="mb-4">
					<h5 style="margin-bottom: 15px; color: #36414C; border-bottom: 2px solid #f39c12; padding-bottom: 8px;">
						<i class="fa fa-cubes"></i> Sub Assembly Items (${so_data.sfg_items.length})
					</h5>
					${render_sfg_table(so_data.sfg_items)}
				</div>

				<!-- RM Items -->
				<div class="mb-4">
					<h5 style="margin-bottom: 15px; color: #36414C; border-bottom: 2px solid #27ae60; padding-bottom: 8px;">
						<i class="fa fa-industry"></i> Raw Materials (${so_data.rm_items.length})
					</h5>
					${render_rm_table(so_data.rm_items)}
				</div>
			</div>
		`;

		tabs_content.append(tab_content);
	});
}



function _duration_label(start_str, end_str, bom) {

    var tool_min = 0;

    frappe.call({
        method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_tool_days',
        args: {
            bom: bom
        },
        async: false, 
        callback: function (r) {
            if (!r.exc) {
                tool_min = r.message || 0;
            }
        }
    });

    if (!start_str || !end_str) return '';

    const s = new Date(start_str);
    const e = new Date(end_str);

    const diff_min = Math.round((e - s) / 60000) + tool_min;

    if (isNaN(diff_min) || diff_min <= 0) return '';

    if (diff_min >= 1440) {
        return '~' + (diff_min / 1440).toFixed(1) + ' days';
    }

    const h = Math.floor(diff_min / 60);
    const m = diff_min % 60;

    return h ? h + 'h ' + m + 'm' : m + 'm';
}

function render_fg_table(items) {
	if (!items || items.length === 0) {
		return '<p class="text-muted">No finished goods items</p>';
	}

	let html = `
		<table class="table table-bordered" style="font-size: 13px;">
			<thead style="background-color: #f5f7fa;">
				<tr>
					<th>Item Code</th>
					<th>Planned Qty</th>
					<th>Mfg Type</th>
					<th>Planned Start Date</th>
					<th>Planned End Date</th>
					<th>Duration / Logic</th>
					<th>BOM</th>
					<th>Warehouse</th>
				</tr>
			</thead>
			<tbody>
	`;

	items.forEach(function(item) {
		const dur = _duration_label(item.planned_start_date, item.custom_planned_end_date, item.bom_no);
		const logic_html = `
			<small class="text-muted">
				Backward from delivery date<br>
				via BOM production mins
				${dur ? '<br><span class="badge badge-light" style="font-size:11px;">' + dur + '</span>' : ''}
			</small>`;
		html += `
			<tr>
				<td><strong>${item.item_code}</strong></td>
				<td>${frappe.format(item.planned_qty, {fieldtype: 'Float'})}</td>
				<td>
					<span class="badge ${item.manufacturing_type === 'In House' ? 'badge-success' : 'badge-info'}">
						${item.manufacturing_type || 'In House'}
					</span>
				</td>
				<td>${frappe.format(item.planned_start_date, {fieldtype: 'Datetime'})}</td>
				<td>${item.custom_planned_end_date ? frappe.format(item.custom_planned_end_date, {fieldtype: 'Datetime'}) : '<span class="text-muted">—</span>'}</td>
				<td>${logic_html}</td>
				<td><small>${item.bom_no || ''}</small></td>
				<td><small>${item.warehouse || ''}</small></td>
			</tr>
		`;
	});

	html += '</tbody></table>';
	return html;
}


function render_sfg_table(items) {
	if (!items || items.length === 0) {
		return '<p class="text-muted">No sub assembly items</p>';
	}

	let html = `
		<table class="table table-bordered" style="font-size: 13px;">
			<thead style="background-color: #f5f7fa;">
				<tr>
					<th>Item Code</th>
					<th>Parent Item</th>
					<th>Qty</th>
					<th>Type</th>
					<th>Schedule Date (Start)</th>
					<th>End Date</th>
					<th>Duration / Logic</th>
					<th>Supplier</th>
					<th>BOM</th>
				</tr>
			</thead>
			<tbody>
	`;

	items.forEach(function(item) {
		const dur = _duration_label(item.schedule_date, item.custom_schedule_end_date, item.bom_no);
		const is_inhouse = (item.type_of_manufacturing || 'In House') === 'In House';
		const parent_note = item.parent_item_code
			? '← from <strong>' + item.parent_item_code + '</strong> start'
			: '← from FG start';
		const logic_note = is_inhouse
			? 'Backward via BOM prod mins'
			: 'Backward via lead time + GRN days';
		const logic_html = `
			<small class="text-muted">
				${parent_note}<br>
				${logic_note}
				${dur ? '<br><span class="badge badge-light" style="font-size:11px;">' + dur + '</span>' : ''}
			</small>`;
		html += `
			<tr>
				<td><strong>${item.production_item}</strong></td>
				<td><small>${item.parent_item_code || '<span class="text-muted">—</span>'}</small></td>
				<td>${frappe.format(item.qty, {fieldtype: 'Float'})}</td>
				<td>
					<span class="badge ${is_inhouse ? 'badge-success' : 'badge-warning'}">
						${item.type_of_manufacturing || 'In House'}
					</span>
				</td>
				<td>${frappe.format(item.schedule_date, {fieldtype: 'Datetime'})}</td>
				<td>${frappe.format(item.custom_schedule_end_date, {fieldtype: 'Datetime'})}</td>
				<td>${logic_html}</td>
				<td><small>${item.supplier || '-'}</small></td>
				<td><small>${item.bom_no || ''}</small></td>
			</tr>
		`;
	});

	html += '</tbody></table>';
	return html;
}


function render_rm_table(items) {
	if (!items || items.length === 0) {
		return '<p class="text-muted">No raw material items</p>';
	}

	let html = `
		<table class="table table-bordered" style="font-size: 13px;">
			<thead style="background-color: #f5f7fa;">
				<tr>
					<th>Item Code</th>
					<th>Quantity</th>
					<th>UOM</th>
					<th>Warehouse</th>
					<th>Order By (Start)</th>
					<th>Receive By (Schedule)</th>
					<th>Lead Time Logic</th>
					<th>Supplier</th>
				</tr>
			</thead>
			<tbody>
	`;

	items.forEach(function(item) {
		// Compute lead time gap between order date and receive date in calendar days
		let lead_note = '';
		if (item.custom_start_date && item.schedule_date) {
			const s = new Date(item.custom_start_date);
			const e = new Date(item.schedule_date);
			const diff_days = Math.round((e - s) / 86400000);
			if (diff_days > 0) {
				lead_note = diff_days + ' cal. days (lead + GRN)';
			}
		}
		const logic_html = `
			<small class="text-muted">
				Order: SFG start − lead − GRN days<br>
				Receive: order + lead + GRN days
				${lead_note ? '<br><span class="badge badge-light" style="font-size:11px;">' + lead_note + '</span>' : ''}
			</small>`;
		const warehouse_display = item.warehouse || '-';
		html += `
			<tr>
				<td><strong>${item.item_code}</strong></td>
				<td>${frappe.format(item.quantity, {fieldtype: 'Float'})}</td>
				<td>${item.uom || ''}</td>
				<td><span class="badge badge-secondary">${warehouse_display}</span></td>
				<td>${frappe.format(item.custom_start_date, {fieldtype: 'Date'})}</td>
				<td>${frappe.format(item.schedule_date, {fieldtype: 'Date'})}</td>
				<td>${logic_html}</td>
				<td><small>${item.custom_supplier || '-'}</small></td>
			</tr>
		`;
	});

	html += '</tbody></table>';
	return html;
}
