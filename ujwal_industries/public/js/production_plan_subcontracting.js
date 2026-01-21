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

frappe.ui.form.on('Production Plan', {
	refresh: function(frm) {
		// Auto-populate suppliers and schedule_dates when form loads
		// But DON'T trigger on every refresh - only when needed
		if (frm.doc.sub_assembly_items && frm.doc.sub_assembly_items.length > 0) {
			// Check if any subcontract item is missing supplier
			const needs_update = frm.doc.sub_assembly_items.some(row =>
				row.type_of_manufacturing === 'Subcontract' && !row.supplier
			);
			if (needs_update) {
				populate_subcontracting_data(frm);
			}
		}

		// Add custom button to recalculate FG dates from sub-assembly changes
		if (frm.doc.sub_assembly_items && frm.doc.sub_assembly_items.length > 0 && !frm.is_new()) {
			frm.add_custom_button(__('Update FG Dates from Sub-Assembly'), function() {
				recalculate_fg_dates_from_subassembly(frm);
			}, __('Sub Assembly Items'));
		}
	},

	// Hook into "Get Sub Assembly Items" button
	get_sub_assembly_items: function(frm) {
		// Wait for items to be added, then populate suppliers and schedule_dates
		setTimeout(() => {
			populate_subcontracting_data(frm);
		}, 500);
	}
});

// Production Plan Item (po_items) events
frappe.ui.form.on('Production Plan Item', {
	planned_start_date: function(frm, cdt, cdn) {
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
	sub_assembly_items_add: function(frm, cdt, cdn) {
		// When new row is added
		populate_supplier_for_row(frm, cdt, cdn);
	},

	production_item: function(frm, cdt, cdn) {
		// When production item changes
		populate_supplier_for_row(frm, cdt, cdn);
		populate_fg_warehouse_for_row(frm, cdt, cdn);
	},

	type_of_manufacturing: function(frm, cdt, cdn) {
		// When type changes
		const row = locals[cdt][cdn];
		if (row.type_of_manufacturing === 'Subcontract' && !row.supplier) {
			populate_supplier_for_row(frm, cdt, cdn);
		} else if (row.type_of_manufacturing !== 'Subcontract') {
			// Clear supplier if not subcontract
			mark_programmatic_update();
			frappe.model.set_value(cdt, cdn, 'supplier', '');
		}
	},

	supplier: function(frm, cdt, cdn) {
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

	schedule_date: function(frm, cdt, cdn) {
		// Skip if this is a programmatic update (to prevent loops)
		if (is_programmatic_change()) {
			return;
		}

		// User manually changed schedule_date
		// Update custom_schedule_end_date based on manufacturing type
		const row = locals[cdt][cdn];

		if (!row.schedule_date) {
			return;
		}

		if (row.type_of_manufacturing === 'Subcontract') {
			// For Subcontract: custom_schedule_end_date = schedule_date + lead_time_days
			update_subcontract_end_date(frm, row);
		} else {
			// For In House: custom_schedule_end_date = schedule_date + production_time
			update_inhouse_end_date(frm, row);
		}
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
		if (row.type_of_manufacturing === 'Subcontract' && row.production_item) {
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
		callback: function(r) {
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
		if (row.type_of_manufacturing === 'Subcontract' && row.production_item) {
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
			callback: function(r) {
				if (r.message) {
					const supplier_map = r.message;

					// Mark as programmatic before setting values
					mark_programmatic_update();

					// Populate supplier field for rows without supplier
					frm.doc.sub_assembly_items.forEach(row => {
						if (row.type_of_manufacturing === 'Subcontract' &&
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
	calculate_inhouse_dates_realtime(frm, fg_dates, true);  // Pass true to store original dates
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
		callback: function(r) {
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
		if (row.type_of_manufacturing === 'Subcontract' && row.production_item) {
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
		callback: function(r) {
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
	if (row.type_of_manufacturing !== 'Subcontract' ||
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
		callback: function(r) {
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
		callback: function(r) {
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
		callback: function(r) {
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
					function() {
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
					function() {
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
function update_subcontract_end_date(frm, row) {
	if (!row.production_item || !row.schedule_date) {
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
		callback: function(r) {
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
		}
	});
}

/**
 * Update custom_schedule_end_date for In House items
 * Formula: custom_schedule_end_date = schedule_date + production_time_minutes
 */
function update_inhouse_end_date(frm, row) {
	if (!row.bom_no || !row.schedule_date || !row.qty) {
		return;
	}

	// Fetch production time from BOM operations
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.production_plan.get_production_time',
		args: {
			bom_no: row.bom_no,
			qty: row.qty
		},
		callback: function(r) {
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
		}
	});
}
