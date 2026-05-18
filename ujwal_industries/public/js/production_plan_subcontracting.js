// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

// Timestamp of last programmatic update - events within 1 second are considered programmatic
let last_programmatic_update = 0;
const PROGRAMMATIC_UPDATE_WINDOW = 1000; // 1 second

function is_programmatic_change() {
	return (Date.now() - last_programmatic_update) < PROGRAMMATIC_UPDATE_WINDOW;
}

function mark_programmatic_update() {
	last_programmatic_update = Date.now();
}

// open_manage_dates_dialog is defined in manage_dates_dialog.js (loaded via app_include_js)
// open_parallel_manage_dates_dialog is defined in parallel_manage_dates_dialog.js (loaded via app_include_js)


frappe.ui.form.on('Production Plan', {
	refresh: function (frm) {
		// Only draft and po_items is available can edit the dates
		if (frm.doc.docstatus === 0 && frm.doc.po_items) {
			frm.add_custom_button(__("Manage Dates"), () => {

				if (frm.doc.custom_parallel_planning === 1) {
					open_parallel_manage_dates_dialog(frm);
					
				} else {
					open_manage_dates_dialog(frm);
				}

			}, __("Actions"));
		}
		// Always Draft and not display want to submit popup box
		if (frm.doc.docstatus === 1) {
			frm.remove_custom_button(__("Material Request"), __("Create"));

			frm.add_custom_button(
				__("Material Request"),
				() => {
					frm.events.create_material_request(frm, 0);
				},
				__("Create")
			);
		}
		frm.set_query("custom_supplier", "po_items", function (doc, cdt, cdn) {
			var row = locals[cdt][cdn];
			if (!row.item_code) {
				return {};
			}
			return {
				query: "ujwal_industries.ujwal_industries.overrides.production_plan.get_item_suppliers_query",
				filters: {
					item_code: row.item_code
				}
			};
		});
		frm.set_query("supplier", "sub_assembly_items", function (doc, cdt, cdn) {
			var row = locals[cdt][cdn];

			if (!row.production_item) {
				return {};
			}

			return {
				query: "ujwal_industries.ujwal_industries.overrides.production_plan.get_item_suppliers_query",
				filters: {
					item_code: row.production_item
				}
			};
		});

	},

	after_save: function (frm) {
		frm.reload_doc();
	},

	before_submit: function (frm) {
		if (frm.ignore_tool_confirm) {
			return;
		}

		frappe.call({
			method: "ujwal_industries.ujwal_industries.overrides.production_plan.validate_tool_limit",
			args: {
				docname: frm.doc.name
			},
			callback: function (r) {

				if (r.message && r.message.length > 0) {

					frappe.validated = false;

					let msg = "<b>Tool Load Limit Exceeded !</b><br>" + r.message.join("");

					frappe.confirm(
						msg,
						function () {
							frm.ignore_tool_confirm = true;
							frm.save('Submit');
						},
						function () {
							frappe.msgprint("Submission Cancelled");
						}
					);

				}
			}
		});
	},

	// Hook into "Get Sub Assembly Items" button
	get_sub_assembly_items: function (frm) {
		// Wait for items to be added, then populate suppliers and schedule_dates
		setTimeout(() => {
			populate_subcontracting_data(frm);
		}, 500);
	},

	// Hook into "Get Items for Material Request" button
	get_items_for_mr: function (frm) {
		// Wait for MR items to be added, then calculate custom dates
		setTimeout(() => {
			calculate_mr_item_dates(frm);
		}, 500);
	},
});

frappe.ui.form.on('Production Plan Item', {
	custom_manufacturing_type: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		if (row.custom_manufacturing_type === 'Subcontract' || row.custom_manufacturing_type === 'In House - Vendor') {

			if (row.item_code) {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_subcontract_updates_client',
					args: {
						item_code: row.item_code,
						company: frm.doc.company,
						sales_order_item: row.sales_order_item
					},
					callback: function (r) {
						if (r.message) {
							mark_programmatic_update();

							if (r.message.custom_supplier && !row.custom_supplier) {
								frappe.model.set_value(cdt, cdn, 'custom_supplier', r.message.custom_supplier);
							}

							if (r.message.planned_start_date && row.custom_manufacturing_type === 'Subcontract') {
								frappe.model.set_value(cdt, cdn, 'planned_start_date', r.message.planned_start_date);
							}
						}
					}
				});
			}
		}
		else if (row.custom_manufacturing_type === 'In House') {
			mark_programmatic_update();
			frappe.model.set_value(cdt, cdn, 'custom_supplier', '');
		}
	},
	planned_start_date: function (frm, cdt, cdn) {
		// Skip if this is a programmatic update (to prevent loops)
		if (is_programmatic_change()) {
			return;
		}

		// When user changes FG planned_start_date, update sub_assembly_items
		const row = locals[cdt][cdn];
		if (row.item_code && row.planned_start_date) {
			update_subassembly_dates_for_fg(frm, row.item_code, row.planned_start_date);
		}
	}
});

// Production Plan Sub Assembly Item events
frappe.ui.form.on('Production Plan Sub Assembly Item', {
	sub_assembly_items_add: function (frm, cdt, cdn) {
		// When new row is added
		populate_supplier_for_row(frm, cdt, cdn);
	},

	production_item: function (frm, cdt, cdn) {
		// When production item changes
		populate_supplier_for_row(frm, cdt, cdn);
		populate_fg_warehouse_for_row(frm, cdt, cdn);
	},

	type_of_manufacturing: function (frm, cdt, cdn) {
		// When type changes
		const row = locals[cdt][cdn];
		if ((row.type_of_manufacturing === 'Subcontract' || row.type_of_manufacturing === 'In House - Vendor') && !row.supplier) {
			populate_supplier_for_row(frm, cdt, cdn);
		} else if (row.type_of_manufacturing !== 'Subcontract' && row.type_of_manufacturing !== 'In House - Vendor') {
			// Clear supplier if not subcontract
			mark_programmatic_update();
			frappe.model.set_value(cdt, cdn, 'supplier', '');
		}
	},

	supplier: function (frm, cdt, cdn) {
		// Skip if this is a programmatic update
		if (is_programmatic_change()) {
			return;
		}

		// When supplier changes, recalculate schedule_date
		const row = locals[cdt][cdn];
		if (row.type_of_manufacturing === 'Subcontract' && row.supplier) {
			recalculate_schedule_dates(frm);
		}
	},

	schedule_date: function (frm, cdt, cdn) {
		// Skip if this is a programmatic update (to prevent loops)
		if (is_programmatic_change()) {
			return;
		}

		// User manually changed schedule_date
		const row = locals[cdt][cdn];

		if (!row.schedule_date) {
			return;
		}

		// Update custom_schedule_end_date based on manufacturing type
		// CASCADE AFTER end_date is updated (in callback) to avoid race condition
		if (row.type_of_manufacturing === 'Subcontract') {
			// For Subcontract: custom_schedule_end_date = schedule_date + lead_time_days
			update_subcontract_end_date(frm, row, function () {
				// Cascade changes to parent SFGs and child MR items AFTER end_date is set
				cascade_sfg_date_change(frm, row);
			});
		} else {
			// For In House: custom_schedule_end_date = schedule_date + production_time
			update_inhouse_end_date(frm, row, function () {
				// Cascade changes to parent SFGs and child MR items AFTER end_date is set
				cascade_sfg_date_change(frm, row);
			});
		}
	},

	custom_schedule_end_date: function (frm, cdt, cdn) {
		// Skip if this is a programmatic update (to prevent loops)
		if (is_programmatic_change()) {
			return;
		}

		// User manually changed custom_schedule_end_date
		const row = locals[cdt][cdn];

		if (!row.custom_schedule_end_date) {
			return;
		}

		// Recalculate schedule_date backward to maintain production/lead time relationship
		if (row.type_of_manufacturing === 'Subcontract') {
			// For Subcontract: schedule_date = end_date - lead_time_days
			if (row.production_item) {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_subcontract_lead_time',
					args: {
						item_code: row.production_item,
						supplier: row.supplier || null,
						company: frm.doc.company
					},
					callback: function (r) {
						if (r.message !== undefined) {
							const lead_time = parseInt(r.message) || 0;

							// Calculate schedule_date backward from end_date
							const new_schedule_date = frappe.datetime.add_days(row.custom_schedule_end_date, -lead_time);

							// Update schedule_date programmatically
							mark_programmatic_update();
							frappe.model.set_value(cdt, cdn, 'schedule_date', new_schedule_date);

							// Cascade changes to parent SFGs and child MR items
							cascade_sfg_date_change(frm, row);
						}
					}
				});
			}
		} else {
			// For In House: schedule_date = end_date - production_minutes
			if (row.bom_no && row.qty) {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_production_time',
					args: {
						bom_no: row.bom_no,
						qty: row.qty
					},
					callback: function (r) {
						if (r.message !== undefined) {
							const production_minutes = parseFloat(r.message) || 0;

							// Calculate schedule_date backward from end_date
							const end_datetime = frappe.datetime.str_to_obj(row.custom_schedule_end_date);
							const schedule_datetime = new Date(end_datetime.getTime() - production_minutes * 60 * 1000);
							const schedule_date_str = frappe.datetime.obj_to_str(schedule_datetime);

							// Update schedule_date programmatically
							mark_programmatic_update();
							frappe.model.set_value(cdt, cdn, 'schedule_date', schedule_date_str);

							// Cascade changes to parent SFGs and child MR items
							cascade_sfg_date_change(frm, row);
						}
					}
				});
			}
		}
	}
});

// Material Request Plan Item events
frappe.ui.form.on('Material Request Plan Item', {
	custom_start_date: function (frm, cdt, cdn) {
		// Skip if this is a programmatic update
		if (is_programmatic_change()) {
			return;
		}

		// When user changes custom_start_date, update schedule_date based on supplier lead time
		const row = locals[cdt][cdn];

		if (!row.custom_start_date || !row.item_code || !row.custom_supplier) {
			return;
		}

		// Get supplier lead time using a custom server method
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_supplier_lead_time',
			args: {
				item_code: row.item_code,
				supplier: row.custom_supplier,
				company: frm.doc.company
			},
			callback: function (r) {
				if (r.message !== undefined && r.message.lead_time_days !== undefined) {
					const lead_time = parseInt(r.message.lead_time_days || 0);

					// Calculate new schedule_date = custom_start_date + lead_time
					const start_date = frappe.datetime.str_to_obj(row.custom_start_date);
					const schedule_date = frappe.datetime.add_days(start_date, lead_time);

					// Update schedule_date programmatically
					mark_programmatic_update();
					frappe.model.set_value(cdt, cdn, 'schedule_date', frappe.datetime.obj_to_str(schedule_date));

					// CASCADE: MR date change should propagate to parent SFG and then to FG
					cascade_mr_date_changes(frm);
				}
			}
		});
	},

	schedule_date: function (frm, cdt, cdn) {
		// Skip if this is a programmatic update
		if (is_programmatic_change()) {
			return;
		}

		// User manually changed schedule_date on MR item
		const row = locals[cdt][cdn];

		if (!row.schedule_date || !row.item_code || !row.custom_supplier) {
			return;
		}

		// Recalculate custom_start_date backward to maintain lead time relationship
		// custom_start_date = schedule_date - lead_time_days
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_supplier_lead_time',
			args: {
				item_code: row.item_code,
				supplier: row.custom_supplier,
				company: frm.doc.company
			},
			callback: function (r) {
				if (r.message !== undefined && r.message.lead_time_days !== undefined) {
					const lead_time = parseInt(r.message.lead_time_days || 0);

					// Calculate custom_start_date backward from schedule_date
					const schedule_date_obj = frappe.datetime.str_to_obj(row.schedule_date);
					const custom_start_date = frappe.datetime.add_days(schedule_date_obj, -lead_time);

					// Update custom_start_date programmatically
					mark_programmatic_update();
					frappe.model.set_value(cdt, cdn, 'custom_start_date', frappe.datetime.obj_to_str(custom_start_date));

					// CASCADE: This should propagate to parent SFG and then to FG
					cascade_mr_date_changes(frm);
				}
			}
		});
	}
});

/**
 * Update sub_assembly_items schedule_dates when FG planned_start_date changes
 */
function update_subassembly_dates_for_fg(frm, fg_item_code, new_planned_date) {
	if (!frm.doc.sub_assembly_items || frm.doc.sub_assembly_items.length === 0) {
		return;
	}

	// Collect subcontract items for this FG
	const subcontract_items = [];
	frm.doc.sub_assembly_items.forEach(row => {
		if ((row.type_of_manufacturing === 'Subcontract' || row.type_of_manufacturing === 'In House - Vendor') && row.production_item) {
			subcontract_items.push(row.production_item);
		}
	});

	if (subcontract_items.length === 0) {
		return;
	}

	// Fetch supplier data to get lead times
	frappe.call({
		method: 'ujwal_industries.api.subcontracting_suppliers.get_default_subcontracting_suppliers',
		args: {
			items: subcontract_items,
			company: frm.doc.company
		},
		callback: function (r) {
			if (r.message) {
				// Build FG dates map with the updated date
				const fg_dates = {};
				(frm.doc.po_items || []).forEach(po_item => {
					if (po_item.item_code && po_item.planned_start_date) {
						fg_dates[po_item.item_code] = po_item.planned_start_date;
					}
				});
				// Ensure the changed item has the new date
				fg_dates[fg_item_code] = new_planned_date;

				// Mark as programmatic before setting values
				mark_programmatic_update();
				calculate_schedule_dates_with_fg(frm, r.message, fg_dates);
				frm.refresh_field('sub_assembly_items');
				frappe.show_alert({
					message: __('Sub assembly schedule dates updated'),
					indicator: 'green'
				}, 3);
			}
		}
	});
}

/**
 * Populate suppliers AND calculate schedule_dates for all sub-assembly items
 * (both Subcontract and In House)
 */
function populate_subcontracting_data(frm) {
	if (!frm.doc.sub_assembly_items || frm.doc.sub_assembly_items.length === 0) {
		return;
	}

	// Collect ALL subcontract items for supplier lookup
	const subcontract_items = [];
	frm.doc.sub_assembly_items.forEach(row => {
		if ((row.type_of_manufacturing === 'Subcontract' || row.type_of_manufacturing === 'In House - Vendor') && row.production_item) {
			subcontract_items.push(row.production_item);
		}
	});

	// Always calculate schedule dates (even if no subcontract items)
	// because there might be In House items

	if (subcontract_items.length > 0) {
		// Batch fetch default suppliers and lead times from server
		frappe.call({
			method: 'ujwal_industries.api.subcontracting_suppliers.get_default_subcontracting_suppliers',
			args: {
				items: subcontract_items,
				company: frm.doc.company
			},
			callback: function (r) {
				if (r.message) {
					const supplier_map = r.message;

					// Mark as programmatic before setting values
					mark_programmatic_update();

					// Populate supplier field for rows without supplier
					frm.doc.sub_assembly_items.forEach(row => {
						if ((row.type_of_manufacturing === 'Subcontract' || row.type_of_manufacturing === 'In House - Vendor') &&
							!row.supplier &&
							row.production_item in supplier_map) {
							frappe.model.set_value(
								row.doctype,
								row.name,
								'supplier',
								supplier_map[row.production_item].supplier
							);
						}
					});

					// Calculate schedule_dates for ALL items (subcontract + in-house)
					calculate_all_schedule_dates(frm, supplier_map);

					frm.refresh_field('sub_assembly_items');
					frappe.show_alert({
						message: __('Schedule dates updated for sub-assembly items'),
						indicator: 'green'
					}, 3);
				}
			}
		});
	} else {
		// No subcontract items, but still calculate In House items
		mark_programmatic_update();
		calculate_all_schedule_dates(frm, {});
		frm.refresh_field('sub_assembly_items');
		frappe.show_alert({
			message: __('Schedule dates updated for in-house items'),
			indicator: 'green'
		}, 3);
	}
}

/**
 * Calculate schedule_dates for ALL sub-assembly items (Subcontract + In House)
 * Calls the server to do the calculation since In House needs BOM operations data
 * Also stores the original dates for later comparison
 */
function calculate_all_schedule_dates(frm, supplier_map) {
	// Just save the form - the server-side hook will handle the calculation
	// The set_subcontracting_suppliers function will calculate both Subcontract and In House items
	// Note: We don't save here - we let the user save when ready
	// The dates will be calculated on before_save hook

	// For immediate feedback, we can still calculate Subcontract items on client
	const fg_dates = {};
	(frm.doc.po_items || []).forEach(po_item => {
		if (po_item.item_code && po_item.planned_start_date) {
			fg_dates[po_item.item_code] = po_item.planned_start_date;
		}
	});

	calculate_schedule_dates_with_fg(frm, supplier_map, fg_dates);

	// For In House items, we need to call the server since we need BOM operations
	// This will calculate and set the dates immediately without saving
	calculate_inhouse_dates_realtime(frm, fg_dates);

	// After all dates are calculated, refresh the original dates for comparison
	// This ensures "Update FG from Sub-Assembly" will detect user changes correctly
	setTimeout(() => {
		refresh_original_subassembly_dates(frm);
	}, 1000);  // Wait for async date calculations to complete
}

/**
 * Calculate schedule_dates for subcontract items based on lead_time_days
 * Uses FG's planned_start_date as base and works backwards through BOM hierarchy
 */
function calculate_schedule_dates(frm, supplier_map) {
	// Build FG item -> planned_start_date map from po_items
	const fg_dates = {};
	(frm.doc.po_items || []).forEach(po_item => {
		if (po_item.item_code && po_item.planned_start_date) {
			fg_dates[po_item.item_code] = po_item.planned_start_date;
		}
	});

	calculate_schedule_dates_with_fg(frm, supplier_map, fg_dates);
}

/**
 * Calculate schedule_dates for In House items using server-side BOM operations
 * Also tracks Subcontract items so their schedule_dates can be used by In House children
 */
function calculate_inhouse_dates_realtime(frm, fg_dates) {
	// Collect ALL sub-assembly items (both In House and Subcontract)
	// We need Subcontract items in the list so the server can track their schedule_dates
	// for use by children In House items
	const all_items = [];
	frm.doc.sub_assembly_items.forEach(row => {
		all_items.push({
			name: row.name,
			production_item: row.production_item,
			parent_item_code: row.parent_item_code,
			type_of_manufacturing: row.type_of_manufacturing,
			bom_no: row.bom_no || null,
			qty: row.qty || 0,
			schedule_date: row.schedule_date || null  // Pass existing schedule_date for Subcontract items
		});
	});

	if (all_items.length === 0) {
		return;
	}

	// Call server to calculate production minutes for In House items
	// The server will use Subcontract items' schedule_dates to calculate children
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.calculate_inhouse_schedule_dates',
		args: {
			production_plan_name: frm.doc.name,
			fg_dates: fg_dates,
			inhouse_items: all_items  // Pass ALL items, not just In House
		},
		callback: function (r) {
			if (r.message) {
				// Apply the calculated schedule dates (only for In House items)
				const calculated_dates = r.message;
				frm.doc.sub_assembly_items.forEach(row => {
					if (row.name in calculated_dates) {
						frappe.model.set_value(
							row.doctype,
							row.name,
							'schedule_date',
							calculated_dates[row.name].schedule_date
						);
						if (calculated_dates[row.name].custom_schedule_end_date) {
							frappe.model.set_value(
								row.doctype,
								row.name,
								'custom_schedule_end_date',
								calculated_dates[row.name].custom_schedule_end_date
							);
						}
					}
				});
				frm.refresh_field('sub_assembly_items');
			}
		}
	});
}

/**
 * Calculate schedule_dates with explicit FG dates map
 * Note: Caller should call mark_programmatic_update() before calling this
 */
function calculate_schedule_dates_with_fg(frm, supplier_map, fg_dates) {
	// Track schedule_date for each production_item as we process
	const schedule_date_map = {};

	// Process items in order (they're ordered by BOM traversal: parent before children)
	frm.doc.sub_assembly_items.forEach(row => {
		const parent_item = row.parent_item_code;

		// Get base date: from FG or from parent's schedule_date
		let base_date;
		if (parent_item in fg_dates) {
			base_date = fg_dates[parent_item];
		} else if (parent_item in schedule_date_map) {
			base_date = schedule_date_map[parent_item];
		} else {
			base_date = row.schedule_date || frm.doc.posting_date || frappe.datetime.now_date();
		}

		if (row.type_of_manufacturing === 'Subcontract') {
			// Get lead_time from supplier_map
			let lead_time = 0;
			if (row.production_item in supplier_map) {
				lead_time = parseInt(supplier_map[row.production_item].lead_time_days) || 0;
			}

			if (lead_time > 0) {
				// Calculate new schedule_date = base_date - lead_time_days
				const new_date = frappe.datetime.add_days(base_date, -lead_time);
				frappe.model.set_value(row.doctype, row.name, 'schedule_date', new_date);
				schedule_date_map[row.production_item] = new_date;
			} else {
				// No lead time, use base_date
				frappe.model.set_value(row.doctype, row.name, 'schedule_date', base_date);
				schedule_date_map[row.production_item] = base_date;
			}
		} else {
			// In-house items: track base_date for children but don't modify schedule_date
			schedule_date_map[row.production_item] = base_date;
		}
	});
}


/**
 * Recalculate schedule_dates when supplier changes
 */
function recalculate_schedule_dates(frm) {
	// Collect all subcontract items
	const subcontract_items = [];
	frm.doc.sub_assembly_items.forEach(row => {
		if ((row.type_of_manufacturing === 'Subcontract' || row.type_of_manufacturing === 'In House - Vendor') && row.production_item) {
			subcontract_items.push(row.production_item);
		}
	});

	if (subcontract_items.length === 0) {
		return;
	}

	// Fetch supplier data again to get lead times
	frappe.call({
		method: 'ujwal_industries.api.subcontracting_suppliers.get_default_subcontracting_suppliers',
		args: {
			items: subcontract_items,
			company: frm.doc.company
		},
		callback: function (r) {
			if (r.message) {
				mark_programmatic_update();
				calculate_schedule_dates(frm, r.message);
				frm.refresh_field('sub_assembly_items');
			}
		}
	});
}

/**
 * Populate supplier for a single row
 */
function populate_supplier_for_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];

	// Only for subcontract items without supplier
	if ((row.type_of_manufacturing !== 'Subcontract' && row.type_of_manufacturing !== 'In House - Vendor') ||
		row.supplier ||
		!row.production_item) {
		return;
	}

	// Fetch default supplier for this item
	frappe.call({
		method: 'ujwal_industries.api.subcontracting_suppliers.get_default_subcontracting_suppliers',
		args: {
			items: [row.production_item],
			company: frm.doc.company
		},
		callback: function (r) {
			if (r.message && row.production_item in r.message) {
				mark_programmatic_update();
				frappe.model.set_value(
					cdt,
					cdn,
					'supplier',
					r.message[row.production_item].supplier
				);
				// After setting supplier, recalculate all schedule_dates
				recalculate_schedule_dates(frm);
			}
		}
	});
}

/**
 * Populate fg_warehouse for a single row from Item Default
 */
function populate_fg_warehouse_for_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];

	// Only if fg_warehouse is not already set and production_item exists
	if (row.fg_warehouse || !row.production_item) {
		return;
	}

	// Fetch default warehouse from Item Default
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_item_default_warehouse',
		args: {
			item_code: row.production_item,
			company: frm.doc.company
		},
		callback: function (r) {
			if (r.message) {
				mark_programmatic_update();
				frappe.model.set_value(cdt, cdn, 'fg_warehouse', r.message);
			}
		}
	});
}

/**
 * Recalculate FG planned_start_dates based on current sub-assembly schedule_dates
 * Shows a single confirmation dialog with all affected FG items
 */
function recalculate_fg_dates_from_subassembly(frm) {
	if (!frm.doc.name || frm.doc.name.startsWith('new-')) {
		frappe.msgprint(__('Please save the Production Plan first'));
		return;
	}

	if (!frm.doc.sub_assembly_items || frm.doc.sub_assembly_items.length === 0) {
		frappe.msgprint(__('No sub-assembly items found'));
		return;
	}

	// Collect all sub-assembly items with their schedule_dates
	const subassembly_data = [];
	frm.doc.sub_assembly_items.forEach(row => {
		if (row.schedule_date && row.production_item && row.parent_item_code) {
			subassembly_data.push({
				name: row.name,
				production_item: row.production_item,
				parent_item_code: row.parent_item_code,
				schedule_date: row.schedule_date,
				custom_schedule_end_date: row.custom_schedule_end_date || null,
				type_of_manufacturing: row.type_of_manufacturing
			});
		}
	});

	if (subassembly_data.length === 0) {
		frappe.msgprint(__('No sub-assembly items with schedule dates found'));
		return;
	}

	// Get original dates from __onload
	const original_dates = frm.doc.__onload && frm.doc.__onload.original_subassembly_dates || {};

	// Call server to calculate FG date impacts
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.calculate_fg_dates_from_subassembly',
		args: {
			production_plan_name: frm.doc.name,
			subassembly_data: subassembly_data,
			original_dates: original_dates
		},
		callback: function (r) {
			if (r.message && r.message.length > 0) {
				const impacts = r.message;

				// Build confirmation message
				let message = __('The following FG items will have their planned start dates updated:') + '<br><br>';
				message += '<table class="table table-bordered" style="margin-top: 10px;">';
				message += '<tr><th>' + __('FG Item') + '</th><th>' + __('Current Date') + '</th><th>' + __('New Date') + '</th></tr>';

				impacts.forEach(impact => {
					message += '<tr>';
					message += '<td>' + impact.fg_item + '</td>';
					message += '<td>' + (impact.current_date ? frappe.datetime.str_to_user(impact.current_date) : '-') + '</td>';
					message += '<td>' + frappe.datetime.str_to_user(impact.new_date) + '</td>';
					message += '</tr>';
				});
				message += '</table>';

				// Show confirmation dialog
				frappe.confirm(
					message,
					function () {
						// User confirmed - update FG planned_start_dates
						mark_programmatic_update();

						impacts.forEach(impact => {
							frm.doc.po_items.forEach(po_item => {
								if (po_item.item_code === impact.fg_item) {
									frappe.model.set_value(
										po_item.doctype,
										po_item.name,
										'planned_start_date',
										impact.new_date
									);
								}
							});
						});

						frm.refresh_field('po_items');
						frappe.show_alert({
							message: __('FG planned start dates updated successfully'),
							indicator: 'green'
						}, 5);
					},
					function () {
						// User cancelled
						frappe.show_alert({
							message: __('Update cancelled'),
							indicator: 'orange'
						}, 3);
					}
				);
			} else {
				frappe.msgprint(__('No changes needed for FG items'));
			}
		}
	});
}

/**
 * Update custom_schedule_end_date for Subcontract items
 * Formula: custom_schedule_end_date = schedule_date + lead_time_days
 */
function update_subcontract_end_date(frm, row, callback) {
	if (!row.production_item || !row.schedule_date) {
		if (callback) callback();
		return;
	}

	// Fetch lead time for this item
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_subcontract_lead_time',
		args: {
			item_code: row.production_item,
			supplier: row.supplier || null,
			company: frm.doc.company
		},
		callback: function (r) {
			if (r.message !== undefined) {
				const lead_time = parseInt(r.message) || 0;

				if (lead_time > 0) {
					// custom_schedule_end_date = schedule_date + lead_time_days
					const end_date = frappe.datetime.add_days(row.schedule_date, lead_time);
					mark_programmatic_update();
					frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', end_date);
				} else {
					// No lead time, end date = schedule date
					mark_programmatic_update();
					frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', row.schedule_date);
				}
			}

			// Call the callback after end_date is set
			if (callback) callback();
		}
	});
}

/**
 * Update custom_schedule_end_date for In House items
 * Formula: custom_schedule_end_date = schedule_date + production_time_minutes
 */
function update_inhouse_end_date(frm, row, callback) {
	if (!row.bom_no || !row.schedule_date || !row.qty) {
		if (callback) callback();
		return;
	}

	// Fetch production time from BOM operations
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_production_time',
		args: {
			bom_no: row.bom_no,
			qty: row.qty
		},
		callback: function (r) {
			if (r.message !== undefined) {
				const production_minutes = parseFloat(r.message) || 0;

				if (production_minutes > 0) {
					// custom_schedule_end_date = schedule_date + production_minutes
					const schedule_datetime = frappe.datetime.str_to_obj(row.schedule_date);
					const end_datetime = new Date(schedule_datetime.getTime() + production_minutes * 60 * 1000);
					const end_date_str = frappe.datetime.obj_to_str(end_datetime);

					mark_programmatic_update();
					frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', end_date_str);
				} else {
					// No production time, end date = schedule date
					mark_programmatic_update();
					frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', row.schedule_date);
				}
			}

			// Call the callback after end_date is set
			if (callback) callback();
		}
	});
}

/**
 * Calculate custom dates for Material Request Plan Items
 * Uses SFG schedule_dates if available, otherwise falls back to FG planned_start_dates
 */
function calculate_mr_item_dates(frm) {
	if (!frm.doc.mr_items || frm.doc.mr_items.length === 0) {
		return;
	}

	// Prepare MR items data
	const mr_items_data = frm.doc.mr_items.map(row => ({
		name: row.name,
		item_code: row.item_code
	}));

	// Call server-side method to calculate dates
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.calculate_mr_item_dates',
		args: {
			production_plan_name: frm.doc.name,
			mr_items_data: mr_items_data
		},
		callback: function (r) {
			if (r.message) {
				const date_map = r.message;

				// Update each MR item with calculated dates
				frm.doc.mr_items.forEach(row => {
					if (row.item_code && date_map[row.item_code]) {
						const dates = date_map[row.item_code];

						mark_programmatic_update();

						// Set custom_start_date (lowest SFG schedule_date)
						if (dates.custom_start_date) {
							frappe.model.set_value(row.doctype, row.name, 'custom_start_date', dates.custom_start_date);
						}

						// Set schedule_date (custom_start_date - lead_time_days)
						if (dates.schedule_date) {
							frappe.model.set_value(row.doctype, row.name, 'schedule_date', dates.schedule_date);
						}

						// Set custom_supplier (default supplier for raw material)
						if (dates.custom_supplier) {
							frappe.model.set_value(row.doctype, row.name, 'custom_supplier', dates.custom_supplier);
						}
					}
				});

				frm.refresh_field('mr_items');
				frappe.show_alert({
					message: __('Material Request dates calculated successfully'),
					indicator: 'green'
				}, 3);

				// Refresh original MR dates for later comparison
				setTimeout(() => {
					refresh_original_mr_dates(frm);
				}, 500);
			}
		}
	});
}

/**
 * Refresh original_mr_dates in __onload after MR item dates are calculated
 * This ensures "Update SFG/FG from Material Request" will correctly detect user changes
 */
function refresh_original_mr_dates(frm) {
	if (!frm.doc.mr_items || frm.doc.mr_items.length === 0) {
		return;
	}

	// Collect current MR items data
	const mr_items_data = frm.doc.mr_items.map(row => ({
		name: row.name,
		item_code: row.item_code,
		custom_start_date: row.custom_start_date || null,
		schedule_date: row.schedule_date || null
	}));

	// Call server to build the original_dates structure
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.refresh_original_mr_dates',
		args: {
			production_plan_name: frm.doc.name || '',
			mr_items_data: mr_items_data
		},
		callback: function (r) {
			if (r.message) {
				// Store in __onload for later comparison
				if (!frm.doc.__onload) {
					frm.doc.__onload = {};
				}
				frm.doc.__onload.original_mr_dates = r.message;
			}
		}
	});
}

/**
 * Update SFG and FG dates based on MR item custom_start_date changes
 */
function update_sfg_fg_dates_from_mr(frm) {
	if (!frm.doc.mr_items || frm.doc.mr_items.length === 0) {
		frappe.msgprint(__('No Material Request items found'));
		return;
	}

	// Get original MR dates from __onload
	const original_dates = frm.doc.__onload && frm.doc.__onload.original_mr_dates || {};

	// Prepare current MR item data
	const mr_items_data = frm.doc.mr_items.map(row => ({
		name: row.name,
		item_code: row.item_code,
		custom_start_date: row.custom_start_date,
		schedule_date: row.schedule_date
	}));

	// Call server to calculate SFG/FG date updates
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.calculate_sfg_fg_dates_from_mr_items',
		args: {
			production_plan_name: frm.doc.name,
			mr_items_data: mr_items_data,
			original_mr_dates: original_dates
		},
		callback: function (r) {
			if (r.message) {
				const sfg_updates = r.message.sfg_updates || [];
				const fg_updates = r.message.fg_updates || [];

				if (sfg_updates.length === 0 && fg_updates.length === 0) {
					frappe.msgprint(__('No date changes detected in Material Request items'));
					return;
				}

				// Build confirmation message
				let message = '<div style="max-height: 400px; overflow-y: auto;">';
				message += '<h4>The following items will be updated:</h4>';

				if (sfg_updates.length > 0) {
					message += '<h5 style="margin-top: 15px;">Sub-Assembly Items:</h5>';
					message += '<table class="table table-bordered" style="font-size: 12px;">';
					message += '<thead><tr><th>Item</th><th>Current Schedule Date</th><th>New Schedule Date</th><th>New End Date</th><th>Triggered By</th></tr></thead><tbody>';

					sfg_updates.forEach(update => {
						const current = frappe.datetime.str_to_user(update.current_date);
						const new_date = frappe.datetime.str_to_user(update.new_date);
						const new_end_date = update.custom_schedule_end_date ? frappe.datetime.str_to_user(update.custom_schedule_end_date) : 'N/A';
						const triggered_by = update.affected_by_material || update.affected_by_sfg || 'N/A';
						message += `<tr><td>${update.production_item}</td><td>${current}</td><td>${new_date}</td><td>${new_end_date}</td><td>${triggered_by}</td></tr>`;
					});

					message += '</tbody></table>';
				}

				if (fg_updates.length > 0) {
					message += '<h5 style="margin-top: 15px;">Finished Goods (FG) Items:</h5>';
					message += '<table class="table table-bordered" style="font-size: 12px;">';
					message += '<thead><tr><th>Item</th><th>Current Date</th><th>New Date</th></tr></thead><tbody>';

					fg_updates.forEach(update => {
						const current = frappe.datetime.str_to_user(update.current_date);
						const new_date = frappe.datetime.str_to_user(update.new_date);
						message += `<tr><td>${update.fg_item}</td><td>${current}</td><td>${new_date}</td></tr>`;
					});

					message += '</tbody></table>';
				}

				message += '</div>';

				// Show confirmation dialog
				frappe.confirm(
					message,
					function () {
						// User clicked Yes - apply updates
						mark_programmatic_update();

						// Update SFG items
						sfg_updates.forEach(update => {
							const row = frm.doc.sub_assembly_items.find(r => r.name === update.row_name);
							if (row) {
								frappe.model.set_value(row.doctype, row.name, 'schedule_date', update.new_date);

								// Also update custom_schedule_end_date if provided
								if (update.custom_schedule_end_date) {
									frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', update.custom_schedule_end_date);
								}
							}
						});

						// Update FG items
						fg_updates.forEach(update => {
							const fg_row = frm.doc.po_items.find(r => r.item_code === update.fg_item);
							if (fg_row) {
								frappe.model.set_value(fg_row.doctype, fg_row.name, 'planned_start_date', update.new_date);
							}
						});

						frm.refresh_fields(['sub_assembly_items', 'po_items']);
						frappe.show_alert({
							message: __('SFG and FG dates updated successfully'),
							indicator: 'green'
						}, 5);
					},
					function () {
						// User clicked No - do nothing
						frappe.show_alert({
							message: __('Update cancelled'),
							indicator: 'orange'
						}, 3);
					}
				);
			}
		}
	});
}


/**
 * Refresh original_subassembly_dates in __onload after dates are calculated
 * This ensures "Update FG from Sub-Assembly" will correctly detect user changes
 */
function refresh_original_subassembly_dates(frm) {
	if (!frm.doc.sub_assembly_items || frm.doc.sub_assembly_items.length === 0) {
		return;
	}

	// Collect current sub-assembly data
	const subassembly_data = [];
	frm.doc.sub_assembly_items.forEach(row => {
		if (row.production_item && row.schedule_date) {
			subassembly_data.push({
				name: row.name,
				production_item: row.production_item,
				parent_item_code: row.parent_item_code,
				schedule_date: row.schedule_date,
				custom_schedule_end_date: row.custom_schedule_end_date || null,
				type_of_manufacturing: row.type_of_manufacturing
			});
		}
	});

	if (subassembly_data.length === 0) {
		return;
	}

	// Call server to build the original_dates structure
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.refresh_original_subassembly_dates',
		args: {
			production_plan_name: frm.doc.name || '',
			subassembly_data: subassembly_data
		},
		callback: function (r) {
			if (r.message) {
				// Store in __onload for later comparison
				if (!frm.doc.__onload) {
					frm.doc.__onload = {};
				}
				frm.doc.__onload.original_subassembly_dates = r.message;
			}
		}
	});
}

/**
 * Cascade SFG schedule_date changes to parent SFGs and child MR items in real-time
 */
function cascade_sfg_date_change(frm, changed_sfg_row) {
	if (!changed_sfg_row.production_item || !changed_sfg_row.schedule_date || !changed_sfg_row.bom_no) {
		return;
	}

	// Call server method to calculate cascade updates
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.cascade_sfg_date_change',
		args: {
			production_plan_name: frm.doc.name,
			changed_sfg_item: changed_sfg_row.production_item,
			changed_sfg_bom: changed_sfg_row.bom_no,
			new_schedule_date: changed_sfg_row.schedule_date,
			new_end_date: changed_sfg_row.custom_schedule_end_date || null,
			company: frm.doc.company,
			changed_sfg_idx: changed_sfg_row.idx
		},
		callback: function (r) {
			if (r.message) {
				const parent_updates = r.message.parent_sfg_updates || [];
				const mr_updates = r.message.mr_item_updates || [];

				// Apply parent SFG updates
				if (parent_updates.length > 0 || mr_updates.length > 0) {
					mark_programmatic_update();
					parent_updates.forEach(update => {
						const row = frm.doc.sub_assembly_items.find(r => r.name === update.row_name);
						if (row) {
							frappe.model.set_value(row.doctype, row.name, 'schedule_date', update.new_schedule_date);
							// Only set custom_schedule_end_date if it's provided and the field exists
							if (update.new_custom_schedule_end_date && 'custom_schedule_end_date' in row) {
								frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', update.new_custom_schedule_end_date);
							}
						}
					});
				}

				// Apply MR item updates
				mr_updates.forEach(update => {
					const row = frm.doc.mr_items.find(r => r.name === update.row_name);
					if (row) {
						frappe.model.set_value(row.doctype, row.name, 'schedule_date', update.new_schedule_date);
						frappe.model.set_value(row.doctype, row.name, 'custom_start_date', update.new_custom_start_date);
					}
				});

				// Refresh tables
				frm.refresh_field('sub_assembly_items');
				frm.refresh_field('mr_items');
			}
		}
	});
}

/**
 * Cascade MR item date changes to parent SFGs and FG items
 */
function cascade_mr_date_changes(frm) {
	if (!frm.doc.mr_items || frm.doc.mr_items.length === 0) {
		return;
	}

	// Collect all current MR item data
	const mr_items_data = frm.doc.mr_items.map(row => ({
		name: row.name,
		item_code: row.item_code,
		custom_start_date: row.custom_start_date || null,
		schedule_date: row.schedule_date || null
	}));

	// Get original MR dates from __onload if available
	const original_mr_dates = (frm.doc.__onload && frm.doc.__onload.original_mr_dates) || {};

	// Call server method to calculate cascade updates
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.calculate_sfg_fg_dates_from_mr_items',
		args: {
			production_plan_name: frm.doc.name,
			mr_items_data: JSON.stringify(mr_items_data),
			original_mr_dates: JSON.stringify(original_mr_dates)
		},
		callback: function (r) {
			if (r.message) {
				const sfg_updates = r.message.sfg_updates || [];
				const fg_updates = r.message.fg_updates || [];

				// Apply SFG updates
				if (sfg_updates.length > 0) {
					mark_programmatic_update();
					sfg_updates.forEach(update => {
						const row = frm.doc.sub_assembly_items.find(r => r.name === update.row_name);
						if (row) {
							frappe.model.set_value(row.doctype, row.name, 'schedule_date', update.new_date);
							// Set custom_schedule_end_date if provided
							if (update.custom_schedule_end_date && 'custom_schedule_end_date' in row) {
								frappe.model.set_value(row.doctype, row.name, 'custom_schedule_end_date', update.custom_schedule_end_date);
							}
						}
					});
					frm.refresh_field('sub_assembly_items');
				}

				// Apply FG updates
				if (fg_updates.length > 0) {
					mark_programmatic_update();
					fg_updates.forEach(update => {
						const row = frm.doc.po_items.find(r => r.item_code === update.fg_item);
						if (row) {
							frappe.model.set_value(row.doctype, row.name, 'planned_start_date', update.new_date);
						}
					});
					frm.refresh_field('po_items');
				}

				// Show message if any updates were made
				if (sfg_updates.length > 0 || fg_updates.length > 0) {
					frappe.show_alert({
						message: `Updated ${sfg_updates.length} SFG and ${fg_updates.length} FG items due to material date change`,
						indicator: 'blue'
					});
				}
			}
		}
	});
}


// ============================================================================
// Bulk Pre Production Plan Reference in Sidebar
// ============================================================================

frappe.ui.form.on('Production Plan', {
	onload_post_render: function (frm) {
		if (frm.doc.name && !frm.doc.__islocal) {
			// Check if this Production Plan is linked to a Bulk Pre Production Plan
			check_and_render_bulk_pp_reference(frm);
		}
	}
});


function check_and_render_bulk_pp_reference(frm) {
	/**
	 * Check if this Production Plan was created from a Bulk Pre Production Plan
	 * and render a sidebar widget with the link
	 */

	frappe.call({
		method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_bulk_pp_for_production_plan',
		args: {
			production_plan: frm.doc.name
		},
		callback: function (r) {
			if (r.message && r.message.bulk_pp) {
				render_bulk_pp_sidebar(frm, r.message);
			}
		}
	});
}


function render_bulk_pp_sidebar(frm, data) {
	/**
	 * Render Bulk Pre Production Plan reference in sidebar
	 */

	if (!data || !data.bulk_pp) return;

	let html = `
		<div class="bulk-pp-sidebar-info" style="margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 5px; border-left: 3px solid #2490ef;">
			<h6 style="margin-bottom: 8px; color: #333; font-weight: 600;">
				<i class="fa fa-link" style="color: #2490ef;"></i> Bulk Production Plan
			</h6>
			<div style="font-size: 12px; line-height: 1.6;">
				<div style="margin-bottom: 4px;">
					<span style="color: #6c757d;">Plan:</span>
					<strong style="color: #333;">${data.bulk_pp}</strong>
				</div>
				${data.sales_order ? `
					<div style="margin-bottom: 4px;">
						<span style="color: #6c757d;">Sales Order:</span>
						<span class="badge badge-primary" style="font-size: 10px;">${data.sales_order}</span>
					</div>
				` : ''}
				${data.posting_date ? `
					<div style="margin-bottom: 4px;">
						<span style="color: #6c757d;">Date:</span>
						<span style="color: #333;">${frappe.format(data.posting_date, { fieldtype: 'Date' })}</span>
					</div>
				` : ''}
				${data.status ? `
					<div style="margin-bottom: 4px;">
						<span style="color: #6c757d;">Status:</span>
						<span class="badge badge-info" style="font-size: 10px;">${data.status}</span>
					</div>
				` : ''}
				<div style="margin-top: 8px;">
					<a href="/app/bulk-pre-production-plan/${data.bulk_pp}" target="_blank" style="font-size: 11px;">
						View Bulk Plan <i class="fa fa-external-link"></i>
					</a>
				</div>
			</div>
		</div>
	`;

	// Add to sidebar - remove existing first to avoid duplicates
	$(frm.wrapper).find('.form-sidebar .bulk-pp-sidebar-info').remove();
	$(frm.wrapper).find('.form-sidebar .sidebar-menu').first().before(html);
}
