// Custom Grid Row Icons for Non-Standard Items
// Adds gear-wide-connected icon and conditional wrench icon for Quotation, Purchase Order, and Sales Order

frappe.provide('ujwal_industries.grid_custom_icons');

ujwal_industries.grid_custom_icons = {
    
	// List of doctypes where custom icons should appear
	applicable_doctypes: ['Production Plan'],

	// List of child table doctypes
	child_table_doctypes: ['Production Plan Item', 'Production Plan Sub Assembly Item'],

	setup: function(frm) {
		// Check if current doctype is applicable
		if (!this.applicable_doctypes.includes(frm.doctype)) {
			return;
		}

		// Check if items grid is available
		if (!frm.fields_dict.sub_assembly_items || !frm.fields_dict.sub_assembly_items.grid) {
			return;
		}

		if (!frm.fields_dict.po_items || !frm.fields_dict.po_items.grid) {
			return;
		}

		// Override grid row rendering for applicable child tables
		const grid_custom = this;

		// Add gear icon to grid header (parent row)
		grid_custom.add_grid_header_icon(frm);

		// Hook into grid rendering for child rows - multiple event listeners for reliability
		frm.fields_dict.po_items.grid.wrapper.find('.grid-body').on('DOMNodeInserted', function(e) {
			
			if ($(e.target).hasClass('grid-row')) {
				// Add slight delay to ensure row is fully rendered
				setTimeout(() => {
					grid_custom.add_custom_icons(frm, $(e.target));
				}, 50);
			}
		});

		frm.fields_dict.sub_assembly_items.grid.wrapper.find('.grid-body').on('DOMNodeInserted', function(e) {
			
			if ($(e.target).hasClass('grid-row')) {
				// Add slight delay to ensure row is fully rendered
				setTimeout(() => {
					grid_custom.add_custom_icons(frm, $(e.target));
				}, 50);
			}
		});

		frm.fields_dict.po_items.grid.wrapper.find('.grid-body').on('DOMNodeInserted', function(e) {
			
			if ($(e.target).hasClass('grid-row')) {
				// Add slight delay to ensure row is fully rendered
				setTimeout(() => {
					grid_custom.add_custom_icons(frm, $(e.target));
				}, 50);
			}
		});

		// Also watch for row additions via MutationObserver on grid body
		const gridBodyObserver = new MutationObserver(function(mutations) {
			mutations.forEach(function(mutation) {
				if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
					mutation.addedNodes.forEach(function(node) {
						if (node.nodeType === 1 && $(node).hasClass('grid-row')) {
							setTimeout(() => {
								grid_custom.add_custom_icons(frm, $(node));
							}, 50);
						}
					});
				}
			});
		});

		const gridBody = frm.fields_dict.sub_assembly_items.grid.wrapper.find('.grid-body .rows')[0];
		if (gridBody) {
			gridBodyObserver.observe(gridBody, { childList: true, subtree: false });
		}

		const gridBody1 = frm.fields_dict.po_items.grid.wrapper.find('.grid-body .rows')[0];
		if (gridBody1) {
			gridBodyObserver.observe(gridBody1, { childList: true, subtree: false });
		}

		// Watch for grid header changes and re-add header icon if needed
		const observer = new MutationObserver(function(mutations) {
			mutations.forEach(function(mutation) {
				if (mutation.type === 'childList') {
					// Check if header icon was removed
					const headerExists = frm.fields_dict.sub_assembly_items.grid.wrapper.find('.grid-header-gear-icon').length > 0;
					if (!headerExists) {
						grid_custom.add_grid_header_icon(frm);
					}
				}
			});
		});

		const observer1 = new MutationObserver(function(mutations) {
			mutations.forEach(function(mutation) {
				if (mutation.type === 'childList') {
					// Check if header icon was removed
					const headerExists = frm.fields_dict.po_items.grid.wrapper.find('.grid-header-gear-icon').length > 0;
					if (!headerExists) {
						grid_custom.add_grid_header_icon(frm);
					}
				}
			});
		});

		// Observe the grid heading row for changes
		const gridHeading = frm.fields_dict.sub_assembly_items.grid.wrapper.find('.grid-heading-row')[0];
		if (gridHeading) {
			observer.observe(gridHeading, { childList: true, subtree: true });
		}

		const gridHeading1 = frm.fields_dict.po_items.grid.wrapper.find('.grid-heading-row')[0];
		if (gridHeading1) {
			observer.observe(gridHeading1, { childList: true, subtree: true });
		}

		// Also add icons to existing rows
		frm.fields_dict.sub_assembly_items.grid.grid_rows.forEach(grid_row => {
			grid_custom.add_custom_icons(frm, $(grid_row.wrapper));
		});

		frm.fields_dict.po_items.grid.grid_rows.forEach(grid_row => {
			grid_custom.add_custom_icons(frm, $(grid_row.wrapper));
		});

	},

	add_grid_header_icon: function(frm) {
		// Check if header icon already added
		if (frm.fields_dict.sub_assembly_items.grid.wrapper.find('.grid-header-gear-icon').length > 0) {
			return;
		}

		// Find the grid heading row (the header row with column titles)
		const $grid_heading_row = frm.fields_dict.sub_assembly_items.grid.wrapper.find('.grid-heading-row .data-row');

		if ($grid_heading_row.length === 0) {
			return;
		}

		// Find the existing gear icon column in the header (the one that shows "gear" icon)
		const $existing_gear_col = $grid_heading_row.find('.col.grid-static-col.d-flex.justify-content-center');

		// Create the header wrench icon column (matching the style of child rows)
		const $header_gear = $(`
			<div class="col grid-static-col d-flex justify-content-center grid-header-gear-icon" style="cursor: pointer;">
				<a>
					${frappe.utils.icon("solid-info", "sm", "", "filter: opacity(0.5)")}
				</a>
			</div>
		`);

		// Add click handler
		$header_gear.on('click', function(e) {
			e.stopPropagation();
		});

		// Insert after the existing gear column (or after the last column if not found)
		if ($existing_gear_col.length > 0) {
			$header_gear.insertAfter($existing_gear_col);
		} else {
			// Fallback: append to the end of the header row
			$grid_heading_row.append($header_gear);
		}



		if (frm.fields_dict.po_items.grid.wrapper.find('.grid-header-gear-icon').length > 0) {
			return;
		}

		const $grid_heading_row1 = frm.fields_dict.po_items.grid.wrapper.find('.grid-heading-row .data-row');

		if ($grid_heading_row1.length === 0) {
			return;
		}

		// Find the existing gear icon column in the header (the one that shows "gear" icon)
		const $existing_gear_col1 = $grid_heading_row1.find('.col.grid-static-col.d-flex.justify-content-center');

		const $header_gear1 = $(`
			<div class="col grid-static-col d-flex justify-content-center grid-header-gear-icon" style="cursor: pointer;">
				<a>
					${frappe.utils.icon("solid-info", "sm", "", "filter: opacity(0.5)")}
				</a>
			</div>
		`);

		// Add click handler
		$header_gear1.on('click', function(e) {
			e.stopPropagation();
		});

		// Insert after the existing gear column (or after the last column if not found)
		if ($existing_gear_col1.length > 0) {
			$header_gear1.insertAfter($existing_gear_col1);
		} else {
			// Fallback: append to the end of the header row
			$grid_heading_row.append($header_gear1);
		}
	},

	add_custom_icons: function(frm, $row) {
		const grid_custom = this;

		// Check if icons already added
		if ($row.find('.custom-gear-icon').length > 0) {
			return;
		}

		// Find the btn-open-row (edit icon) - the last column
		const $edit_col = $row.find('.btn-open-row').closest('.col');

		if ($edit_col.length === 0) {
			return;
		}

		// Create custom icon column
		const $custom_col = $(`
			<div class="col grid-static-col d-flex justify-content-center flex-column align-items-center custom-gear-icon"
				 style="cursor: pointer; padding: 4px 8px !important; border: 0px !important;">
				<a class="gear-wide-icon">
					${frappe.utils.icon("solid-info", "sm", "", "filter: opacity(0.5)")}
				</a>
				
			</div>
		`);

		// <a class="wrench-icon" style="display: none; margin-top: 2px;">
		// 			${frappe.utils.icon("tool", "sm", "", "filter: opacity(0.5)")}
		// 		</a>

		// Insert AFTER the edit icon (btn-open-row)
		$custom_col.insertAfter($edit_col);

		// Get the row data
		const row_name = $row.data('name');
		if (!row_name) {
			return;
		}

		// Check if item is non-standard and update wrench icon visibility
		grid_custom.update_wrench_icon(frm, row_name, $custom_col);

		// Add click handler for gear icon
		$custom_col.find('.gear-wide-icon').on('click', function(e) {
			e.stopPropagation();
			grid_custom.handle_gear_click(frm, row_name);
		});

		// Add click handler for wrench icon
		$custom_col.find('.wrench-icon').on('click', function(e) {
			e.stopPropagation();
			grid_custom.handle_wrench_click(frm, row_name);
		});

		// Watch for item_code changes
		frappe.model.on('sub_assembly_items', 'production_item', function(frm, cdt, cdn) {
			if (cdn === row_name) {
				grid_custom.update_wrench_icon(frm, row_name, $custom_col);
			}
		});

		frappe.model.on('po_items', 'item_code', function(frm, cdt, cdn) {
			if (cdn === row_name) {
				grid_custom.update_wrench_icon(frm, row_name, $custom_col);
			}
		});
	},

	update_wrench_icon: function(frm, row_name, $custom_col) {
		// Get the row
		const row = frappe.get_doc(frm.fields_dict.sub_assembly_items.grid.doctype, row_name);
		$custom_col.find('.wrench-icon').show();

		const row1 = frappe.get_doc(frm.fields_dict.po_items.grid.doctype, row_name);
		$custom_col.find('.wrench-icon').show();

		// if (!row || !row.item_code) {
		// 	$custom_col.find('.wrench-icon').hide();
		// 	return;
		// }

		// Fetch item details to check is_non_standard
		// frappe.db.get_value('Production Plan Sub Assembly Item', row.item_code, 'is_non_standard', (r) => {
		// 	$custom_col.find('.wrench-icon').show();
			// if (r && r.is_non_standard === 0) {
			// 	// Show wrench icon for non-standard items (when is_non_standard = 0)
			// 	$custom_col.find('.wrench-icon').show();
			// } else {
			// 	$custom_col.find('.wrench-icon').hide();
			// }
		// });
	},

	handle_gear_click: function(frm, row_name) {
		const row = frappe.get_doc(frm.fields_dict.sub_assembly_items.grid.doctype, row_name);
		// 1. Check if item_code is selected
		if(row != undefined){
		
			if (!row.production_item) {
				frappe.msgprint({
					title: __('Item Required'),
					message: __('Please select an Production first'),
					indicator: 'red'
				});
				return;
			}

			// 2. Fetch item details and check if it's already a non-standard item
			frappe.call({
				method: 'frappe.client.get',
				args: {
					doctype: 'Item',
					name: row.production_item,
					fields: ['*']  // Fetch all fields including custom fields
				},
				callback: function(r) {
					if (r.message) {
						const item = r.message;

						ujwal_industries.grid_custom_icons.show_non_standard_dialog(frm, row, item,'sub_assembly_items');
						// Check if item is already non-standard
						// if (item.is_non_standard === 1 || item.is_non_standard === '1') {
						// 	// This is a non-standard item, fetch its configuration and show discount dialog
						// 	ujwal_industries.grid_custom_icons.show_existing_non_standard_item(frm, row, item);
						// 	return;
						// }

						// // 3. If not non-standard, create stepper dialog
						// ujwal_industries.grid_custom_icons.show_non_standard_dialog(frm, row, item);
					}
				}
			});
		}




		const row1 = frappe.get_doc(frm.fields_dict.po_items.grid.doctype, row_name);

		// 1. Check if item_code is selected
		if(row1 != undefined){

			if (!row1.item_code) {
				frappe.msgprint({
					title: __('Item Required'),
					message: __('Please select an Production first'),
					indicator: 'red'
				});
				return;
			}

			// 2. Fetch item details and check if it's already a non-standard item
			frappe.call({
				method: 'frappe.client.get',
				args: {
					doctype: 'Item',
					name: row1.item_code,
					fields: ['*']  // Fetch all fields including custom fields
				},
				callback: function(r) {
					if (r.message) {
						const item = r.message;

						ujwal_industries.grid_custom_icons.show_non_standard_dialog(frm, row1, item, 'po_items');
						// Check if item is already non-standard
						// if (item.is_non_standard === 1 || item.is_non_standard === '1') {
						// 	// This is a non-standard item, fetch its configuration and show discount dialog
						// 	ujwal_industries.grid_custom_icons.show_existing_non_standard_item(frm, row, item);
						// 	return;
						// }

						// // 3. If not non-standard, create stepper dialog
						// ujwal_industries.grid_custom_icons.show_non_standard_dialog(frm, row, item);
					}
				}
			});
	}
	},

	show_existing_non_standard_item: function(frm, row, item) {
		// Fetch Non Standard Item Creation record for this item
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Item Creation',
				filters: {
					new_item_code: item.item_code,
					docstatus: 1
				},
				fields: ['name'],
				limit: 1
			},
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					const ns_item_name = r.message[0].name;

					// Fetch full record
					frappe.call({
						method: 'frappe.client.get',
						args: {
							doctype: 'Non Standard Item Creation',
							name: ns_item_name
						},
						callback: function(r2) {
							if (r2.message) {
								// Create dialog showing parameters and discount input
								ujwal_industries.grid_custom_icons.show_ns_item_discount_dialog(frm, r2.message, row);
							}
						}
					});
				} else {
					frappe.msgprint({
						title: __('Not Found'),
						message: __('No Non-Standard Item Creation record found for: {0}', [item.item_code]),
						indicator: 'red'
					});
				}
			}
		});
	},

	show_ns_item_discount_dialog: function(frm, ns_record, row) {
		// Same logic as show_selected_config_discount_step - fetch latest price log and render
		const parent_doctype = frm ? frm.doctype : null;

		// Build filters
		let filters = {
			non_standard_item: ns_record.name
		};

		if (parent_doctype) {
			filters.reference_doctype = parent_doctype;
		}

		// Fetch latest price log
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Price Log Entry',
				filters: filters,
				fields: ['discount_parameter', 'discount_percentage', 'final_price', 'created_on', 'reference_doctype', 'reference_name'],
				order_by: 'created_on desc',
				limit: 1
			},
			callback: function(r) {
				let latest_discount_after = ns_record.apply_discount_after || '';
				let latest_discount_percentage = 0;
				let latest_final_price = ns_record.valuation_price;
				let log_source = '';

				if (r.message && r.message.length > 0) {
					const latest_log = r.message[0];
					latest_discount_after = latest_log.discount_parameter || '';
					latest_discount_percentage = latest_log.discount_percentage || 0;
					latest_final_price = latest_log.final_price || ns_record.valuation_price;

					if (latest_log.reference_doctype && latest_log.reference_name) {
						log_source = `${latest_log.reference_doctype}: ${latest_log.reference_name}`;
					}
				}

				// Render the dialog
				ujwal_industries.grid_custom_icons.render_ns_item_dialog_with_discount(frm, ns_record, latest_discount_after, latest_discount_percentage, latest_final_price, log_source, row);
			}
		});
	},

	render_ns_item_dialog_with_discount: function(frm, ns_record, discount_after, discount_percentage, final_price, log_source, row) {
		// Build parameters HTML
		const parameters = ns_record.parameters || [];
		let parametersHtml = '';

		if (parameters.length > 0) {
			parametersHtml = '<div style="margin-bottom: 20px;"><div style="font-size: 13px; font-weight: 700; color: #36414c; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;"><i class="fa fa-sliders" style="color: #667eea;"></i><span>Configuration Parameters</span></div><div style="display: grid; gap: 8px;">';

			parameters.forEach(param => {
				const pricingValue = param.pricing_type === 'Percentage'
					? `${param.price_percentage || 0}%`
					: (param.pricing_type === 'Fixed Amount' ? format_currency(param.price_amount || 0, 'INR') : 'Both');

				parametersHtml += `
					<div style="background: #f8f9fa; padding: 12px; border-radius: 6px; border: 1px solid #e8ebed; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; align-items: center;">
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PARAMETER</div>
							<div style="font-size: 12px; font-weight: 700; color: #36414c;">${param.parameter}</div>
						</div>
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">VALUE</div>
							<div style="background: #e8f5e9; color: #2e7d32; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
								${param.selected_value}
							</div>
						</div>
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PRICE</div>
							<div style="background: #e3f2fd; color: #1976d2; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
								${pricingValue}
							</div>
						</div>
					</div>
				`;
			});
			parametersHtml += '</div></div>';
		}

		// Build discount info HTML
		const discountInfoHtml = log_source ? `<div style="font-size: 11px; color: #6c7680; margin-bottom: 10px; padding: 8px; background: #e8f5e9; border-radius: 4px;"><i class="fa fa-info-circle" style="color: #48bb78;"></i> Last used in: <strong>${log_source}</strong></div>` : '';
		const previouslyUsedBadge = discount_percentage > 0 ? '<span style="background: #48bb78; color: white; padding: 4px 10px; border-radius: 12px; font-size: 10px; margin-left: auto;">PREVIOUSLY USED</span>' : '';

		// Create the dialog
		const dialog = new frappe.ui.Dialog({
			title: __('Non-Standard Item - {0}', [ns_record.new_item_code]),
			size: 'large',
			fields: [
				{
					fieldname: 'details_html',
					fieldtype: 'HTML',
					options: `
						<div style="background: linear-gradient(135deg, #48bb78 0%, #2e7d32 100%); padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; color: white;">
							<div style="display: flex; justify-content: space-between; align-items: center;">
								<div>
									<div style="font-size: 11px; opacity: 0.9; margin-bottom: 4px;">NON-STANDARD ITEM</div>
									<div style="font-size: 16px; font-weight: 700;">${ns_record.new_item_code}</div>
									<div style="font-size: 12px; opacity: 0.8; margin-top: 2px;">${ns_record.brand} • Frame: ${ns_record.frame_size || 'N/A'}</div>
								</div>
								<div style="text-align: right;">
									<div style="font-size: 11px; opacity: 0.9;">VALUATION PRICE</div>
									<div style="font-size: 20px; font-weight: 800;">${format_currency(ns_record.valuation_price || 0, 'INR')}</div>
								</div>
							</div>
						</div>
						${parametersHtml}
						<div style="background: #fff3e0; padding: 15px; border-radius: 8px; border-left: 3px solid #ff9800; margin-bottom: 15px;">
							<div style="font-size: 13px; font-weight: 700; color: #36414c; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
								<i class="fa fa-percent" style="color: #ff9800;"></i>
								<span>Discount Information</span>
								${previouslyUsedBadge}
							</div>
							${discountInfoHtml}
						</div>
						<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px 20px; border-radius: 8px; color: white; margin-bottom: 15px;">
							<div style="display: flex; justify-content: space-between; align-items: center;">
								<div>
									<div style="font-size: 11px; opacity: 0.9; margin-bottom: 4px;">FINAL PRICE (WITH DISCOUNT)</div>
									<div style="font-size: 14px; font-weight: 600; opacity: 0.9;">This price will be added to your ${frm ? frm.doctype : 'document'}</div>
								</div>
								<div style="text-align: right;">
									<div style="font-size: 24px; font-weight: 800;">${format_currency(final_price, 'INR')}</div>
								</div>
							</div>
						</div>
					`
				},
				{
					fieldname: 'section_break',
					fieldtype: 'Section Break',
					label: __('Apply Discount')
				},
				{
					fieldname: 'apply_discount_after',
					label: __('Apply Discount After'),
					fieldtype: 'Select',
					options: ns_record.brand === 'Siemens' ? 'Absolute Amount' : '\nPercentage Values',
					default: ns_record.brand === 'Siemens' ? 'Absolute Amount' : (discount_after || 'Percentage Values')
				},
				{
					fieldname: 'discount_percentage',
					label: __('Discount Percentage (%)'),
					fieldtype: 'Float',
					default: discount_percentage,
					depends_on: 'apply_discount_after'
				}
			],
			primary_action_label: __('Apply New Discount'),
			primary_action: function(values) {
				ujwal_industries.grid_custom_icons.apply_discount_and_close(ns_record.name, values, dialog, frm, true);
			},
			secondary_action_label: discount_percentage > 0 ? __('Add Item (Use Existing)') : null,
			secondary_action: discount_percentage > 0 ? function() {
				// Directly add item without creating new log entry
				ujwal_industries.grid_custom_icons.add_item_to_grid_directly(ns_record, final_price, dialog, frm);
			} : null
		});

		// Store references for later use
		dialog.ns_record = ns_record;
		dialog.parent_frm = frm;
		dialog.original_row = row;
		dialog.original_discount_after = discount_after;
		dialog.original_discount_percentage = discount_percentage;
		dialog.original_final_price = final_price;

		dialog.show();
	},

	add_item_to_grid_directly: function(ns_record, final_price, dialog, frm) {
		// Directly add item to grid without creating new log entry
		const new_item_code = ns_record.new_item_code;

		if (frm && dialog.original_row && new_item_code) {
			const original_row = dialog.original_row;

			frappe.show_alert({
				message: __('Adding item with existing discount: {0}', [format_currency(final_price, 'INR')]),
				indicator: 'blue'
			}, 5);

			// First set the item_code - this will trigger item details fetch
			frappe.model.set_value(original_row.doctype, original_row.name, 'item_code', new_item_code).then(() => {
				// After item details are fetched, override the rate with our discounted price
				setTimeout(() => {
					frappe.model.set_value(original_row.doctype, original_row.name, 'rate', final_price);
					frappe.model.set_value(original_row.doctype, original_row.name, 'qty', 1);

					// Refresh the grid to show the new values
					frm.fields_dict.sub_assembly_items.grid.refresh();
					frm.refresh_field('sub_assembly_items');

					frm.fields_dict.po_items.grid.refresh();
					frm.refresh_field('po_items');
				}, 500);
			});

			dialog.hide();
		}
	},

	apply_discount_and_close: function(ns_item_name, values, dialog, frm, force_new_log) {
		// Check if discount values have actually changed
		const discount_changed = force_new_log ||
			(values.apply_discount_after !== dialog.original_discount_after) ||
			(values.discount_percentage !== dialog.original_discount_percentage);

		if (!discount_changed) {
			// Values haven't changed, just add item directly
			const ns_record = dialog.ns_record || dialog.selected_config;
			const final_price = dialog.original_final_price;
			ujwal_industries.grid_custom_icons.add_item_to_grid_directly(ns_record, final_price, dialog, frm);
			return;
		}

		// Call server method to update discount and create new log entry
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.non_standard_item_creation.non_standard_item_creation.update_discount',
			args: {
				docname: ns_item_name,
				apply_discount_after: values.apply_discount_after || null,
				discount_percentage: values.discount_percentage || 0,
				reference_doctype: frm.doctype,
				reference_name: frm.doc.name
			},
			callback: function(r) {
				if (r.message && r.message.success) {
					const final_price = r.message.new_price;
					const ns_record = dialog.ns_record || dialog.selected_config;
					const new_item_code = ns_record ? ns_record.new_item_code : null;

					frappe.show_alert({
						message: __('Discount applied successfully. Final price: {0}', [format_currency(final_price, 'INR')]),
						indicator: 'green'
					}, 5);

					// Add the non-standard item to the items child table
					if (frm && dialog.original_row && new_item_code) {
						const original_row = dialog.original_row;

						// First set the item_code - this will trigger item details fetch
						frappe.model.set_value(original_row.doctype, original_row.name, 'item_code', new_item_code).then(() => {
							// After item details are fetched, override the rate with our discounted price
							setTimeout(() => {
								frappe.model.set_value(original_row.doctype, original_row.name, 'rate', final_price);
								frappe.model.set_value(original_row.doctype, original_row.name, 'qty', 1);

								// Refresh the grid to show the new values
								frm.fields_dict.sub_assembly_items.grid.refresh();
								frm.refresh_field('sub_assembly_items');

								frm.fields_dict.po_items.grid.refresh();
								frm.refresh_field('po_items');
							}, 500);
						});
					}

					dialog.hide();
				}
			},
			error: function(err) {
				frappe.msgprint(__('Error applying discount: {0}', [err.message || err]));
			}
		});
	},

	show_non_standard_dialog: function(frm, row, item, from_doctype) {
		const grid_custom = this;

		// Create stepper dialog with custom size - SINGLE HTML FIELD
		const dialog = new frappe.ui.Dialog({
			title: __('Tool Allocation Details'),
			size: 'extra-large',
			fields: [
				{
					fieldname: 'dialog_container',
					fieldtype: 'HTML'
				}
			],
			// primary_action_label: __('Next →'),
			
			primary_action: function() {
				// // Handle step navigation
				// if (dialog.current_step === 1) {
				// 	grid_custom.show_step_2(dialog, row.item_code);
				// } else {
				dialog.hide();
				// }
			},
			// secondary_action_label: __('← Back'),
			// secondary_action: function() {
			// 	if (dialog.current_step === 2) {
			// 		grid_custom.show_step_1(dialog, item, row.item_code);
			// 	}
			// }
		});

		dialog.current_step = 1;
		dialog.item = item;
		dialog.item_code = row.item_code;
		dialog.parent_frm = frm;  // Store parent form reference for logging
		dialog.original_row = row;  // Store original row reference for updating

		// Style the modal - remove padding from modal-body to allow stepper full width
		dialog.$wrapper.find('.modal-content').css({
			'border-radius': '12px',
			'overflow': 'hidden'
		});

		// Remove padding from modal-body and form container for stepper
		dialog.$wrapper.find('.modal-body').css({
			'padding': '0'
		});

		dialog.fields_dict.dialog_container.$wrapper.css({
			'margin': '0',
			'padding': '0'
		});

		// Hide back button initially
		dialog.$wrapper.find('.btn-modal-secondary').hide();

		// Show Step 1 - Item Details
		grid_custom.show_step_1(dialog, frm.doc.name, item, row.bom_no, row.name,from_doctype);

		dialog.show();
	},

	get_stepper_html: function(current_step, progress_percent) {
		return `
			<div class="stepper-container">
				<div class="stepper-progress">
					<div class="progress-line" style="width: ${progress_percent}%;"></div>
					<div class="step ${current_step === 1 ? 'active' : 'completed'}">
						<div class="step-circle">
							<span class="step-number">1</span>
						</div>
						<div class="step-label">Item Details</div>
						<div class="step-description">Base Information</div>
					</div>
					<div class="step ${current_step === 2 ? 'active' : ''}">
						<div class="step-circle">
							<span class="step-number">2</span>
						</div>
						<div class="step-label">Existing Records</div>
						<div class="step-description">Previous Configurations</div>
					</div>
				</div>
			</div>
		`;
	},

	show_step_1: function(dialog, doc_name, item, bom_no,row_name, from_doctype) {
		// Update step to 1
		dialog.current_step = 1;

		// Update buttons
		dialog.set_primary_action(__('Close'), function() {
			dialog.hide();
		});
		// dialog.$wrapper.find('.btn-modal-secondary').hide();

		// Show loading state first
		dialog.fields_dict.dialog_container.$wrapper.html(`
			<div class="text-center" style="padding: 40px;">
				<i class="fa fa-spinner fa-spin fa-2x text-muted"></i>
				<p class="text-muted" style="margin-top: 10px; font-size: 13px;">Loading item details...</p>
			</div>
		`);

		// Fetch item price for the brand and item_code
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.tool_limit.tool_conflict',
			args: {
				'name' : doc_name,
				'bom': bom_no,
				'row_name': row_name,
				'from_doctype': from_doctype
			},
			callback: function(r) {
				if(r.message.length==0){
					var html = `<div style="text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;"
					>No Conflict Found </div>`;
				}
				else{
				// Build Step 1 HTML - Include stepper + content in single container
				// ${ujwal_industries.grid_custom_icons.get_stepper_html(1, 0)}
				let rows = "";

				for (let i = 0; i < r.message.length; i++) {
					rows += `
						<tr>
							<td style="font-size: 9px; text-align: center;">${r.message[i].bom_no}</td>
							<td style="font-size: 9px; text-align: center;">${r.message[i].operation}</td>
							<td style="font-size: 9px; text-align: center;">${r.message[i].tool}</td>
							<td style="font-size: 9px; text-align: center;">${r.message[i].name}</td>
						</tr>
					`;
				}
				var html = `
					
					<div class="non-standard-item-details" style="padding: 20px; background: #ffffff;">
						

						<div class="row" style="display: block; margin-top: 15px;">
							
							 <h3>Tool Allocation Against Active Production Plan</h3>
							<center class="t1" style="border:none">
							<table width="100%" border="1" cellspacing="0" cellpadding="5">
								<tr style="text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
									<th style="font-size: 12px; ">BOM</th>
									<th style="font-size: 12px; ">Operation</th>
									<th style="font-size: 12px; ">Tool</th>
									<th style="font-size: 12px; ">Active Production Plan</th>
								</tr>
							    
								${rows}
								</table></center>
							
						</div>

					</div>
				`;
				}

				dialog.fields_dict.dialog_container.$wrapper.html(html);
			}
		});
	},

	show_step_2: function(dialog, base_item_code) {
		dialog.current_step = 2;

		// Update buttons - show back and change primary to close
		dialog.set_primary_action(__('Close'), function() {
			dialog.hide();
		});
		dialog.$wrapper.find('.btn-modal-secondary').show();

		// Show loading state with stepper
		const loadingHtml = `
			${ujwal_industries.grid_custom_icons.get_stepper_html(2, 60)}
			<div class="text-center" style="padding: 40px;">
				<i class="fa fa-spinner fa-spin fa-2x text-muted"></i>
				<p class="text-muted" style="margin-top: 10px; font-size: 13px;">Loading configurations...</p>
			</div>
		`;
		dialog.fields_dict.dialog_container.$wrapper.html(loadingHtml);

		// Fetch existing Non Standard Item Creation records with parameters
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Item Creation',
				filters: {
					base_item: base_item_code,
					docstatus: 1
				},
				fields: ['name', 'new_item_code', 'valuation_price', 'creation', 'modified'],
				limit_page_length: 0,
				order_by: 'modified desc'
			},
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					// Fetch parameters for each record
					ujwal_industries.grid_custom_icons.render_step_2_with_parameters(dialog, r.message);
				} else {
					ujwal_industries.grid_custom_icons.render_step_2_empty(dialog);
				}
			}
		});
	},

	render_step_2_empty: function(dialog) {
		const base_item_code = dialog.item_code;

		const html = `
			${ujwal_industries.grid_custom_icons.get_stepper_html(2, 60)}
			<div class="non-standard-existing-records" style="padding: 20px; background: #ffffff;">
				<div style="text-align: center; padding: 50px 20px; background: #f8f9fa; border-radius: 8px; border: 2px dashed #dee2e6;">
					<i class="fa fa-folder-open-o" style="font-size: 48px; color: #d1d8dd; margin-bottom: 15px;"></i>
					<h4 style="color: #6c7680; margin-bottom: 8px; font-weight: 600; font-size: 16px;">No Configurations Found</h4>
					<p style="color: #a8b3ba; font-size: 13px; margin-bottom: 20px;">No existing configurations for this item</p>
					<button class="btn-create-new-config-empty" data-base-item="${base_item_code}" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; font-weight: 600; padding: 10px 24px; border-radius: 6px; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; transition: all 0.2s; box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);">
						<i class="fa fa-plus-circle"></i>
						<span>Create New Configuration</span>
					</button>
				</div>
			</div>
		`;
		dialog.fields_dict.dialog_container.$wrapper.html(html);

		// Attach event listener to "Create New" button in empty state
		setTimeout(() => {
			const createBtn = dialog.$wrapper.find('.btn-create-new-config-empty');
			if (createBtn.length) {
				createBtn.on('click', function() {
					const base_item = $(this).data('base-item');
					ujwal_industries.grid_custom_icons.create_new_non_standard_item(base_item, dialog);
				});

				// Add hover effect
				createBtn.on('mouseenter', function() {
					$(this).css({
						'transform': 'translateY(-2px)',
						'box-shadow': '0 4px 16px rgba(102, 126, 234, 0.4)'
					});
				}).on('mouseleave', function() {
					$(this).css({
						'transform': 'translateY(0)',
						'box-shadow': '0 2px 8px rgba(102, 126, 234, 0.3)'
					});
				});
			}
		}, 100);
	},

	render_step_2_with_parameters: function(dialog, records) {
		let completed = 0;
		const total = records.length;
		const record_details = [];

		records.forEach((record) => {
			frappe.call({
				method: 'frappe.client.get',
				args: {
					doctype: 'Non Standard Item Creation',
					name: record.name
				},
				callback: function(r) {
					if (r.message) {
						record_details.push(r.message);
					}
					completed++;

					if (completed === total) {
						ujwal_industries.grid_custom_icons.render_step_2_html(dialog, record_details);
					}
				}
			});
		});
	},

	render_step_2_html: function(dialog, records) {
		const base_item_code = dialog.item_code;

		let html = `
			${ujwal_industries.grid_custom_icons.get_stepper_html(2, 60)}
			<div class="non-standard-existing-records" style="padding: 20px; background: #ffffff;">
				<div class="compact-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 10px 16px; border-radius: 6px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;">
					<div class="header-info" style="display: flex; align-items: center; gap: 8px; color: white; font-size: 13px;">
						<i class="fa fa-check-circle"></i>
						<span style="background: rgba(255, 255, 255, 0.3); padding: 3px 10px; border-radius: 10px; font-weight: 600;">${records.length}</span>
						<span style="font-weight: 600;">Select Existing or Create New</span>
					</div>
					<div style="display: flex; gap: 10px;">
						<button class="btn-select-config" style="background: #48bb78; color: white; font-weight: 600; padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer; display: none; align-items: center; gap: 6px; transition: all 0.2s;">
							<i class="fa fa-check"></i>
							<span>Select</span>
						</button>
						<button class="btn-create-new-config" data-base-item="${base_item_code}" style="background: white; color: #667eea; font-weight: 600; padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s;">
							<i class="fa fa-plus-circle"></i>
							<span>Create New</span>
						</button>
					</div>
				</div>

				<div style="margin-top: 12px; max-height: 400px; overflow-y: auto;">
		`;

		records.forEach((record, index) => {
			const parameters = record.parameters || [];
			const hasParameters = parameters.length > 0;

			html += `
				<div class="config-card-advanced" data-record="${record.name}" style="background: white; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-left: 4px solid #d1d8dd; overflow: hidden; transition: all 0.2s ease;">
					<div class="config-card-header" style="background: #f8f9fa; padding: 12px 15px; border-bottom: 1px solid #e8ebed; cursor: pointer;"
						 onclick="this.parentElement.querySelector('.config-card-body').classList.toggle('expanded')">
						<div style="display: flex; justify-content: space-between; align-items: center; gap: 10px;">
							<div style="display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0;">
								<input type="radio" name="config_selection" value="${record.name}" class="config-radio" style="width: 18px; height: 18px; cursor: pointer; flex-shrink: 0;" onclick="event.stopPropagation()">
								<span style="background: #48bb78; color: white; padding: 4px 10px; border-radius: 12px; font-size: 10px; font-weight: 700; flex-shrink: 0;">
									#${index + 1}
								</span>
								<div style="min-width: 0; flex: 1;">
									<div style="font-size: 13px; font-weight: 700; color: #36414c; display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
										${record.new_item_code || 'N/A'}
										<i class="fa fa-external-link" style="font-size: 10px; color: #3498db; cursor: pointer; flex-shrink: 0;" onclick="event.stopPropagation(); window.open('/app/non-standard-item-creation/${record.name}', '_blank')"></i>
									</div>
								</div>
							</div>
							<div style="text-align: right; flex-shrink: 0;">
								<div style="font-size: 16px; font-weight: 800; color: #48bb78;">${format_currency(record.valuation_price || 0, 'INR')}</div>
							</div>
							<div style="flex-shrink: 0;">
								<i class="fa fa-chevron-down" style="color: #6c7680; font-size: 12px; transition: transform 0.2s;"></i>
							</div>
						</div>

						${hasParameters ? `
							<div style="margin-top: 8px;">
								<span style="background: #fff3cd; color: #856404; padding: 3px 8px; border-radius: 10px; font-size: 10px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;">
									<i class="fa fa-sliders"></i>
									${parameters.length} Param${parameters.length !== 1 ? 's' : ''}
								</span>
							</div>
						` : ''}
					</div>

					<div class="config-card-body" style="max-height: 0; overflow: hidden; transition: max-height 0.3s ease;">
						<div style="padding: 12px; background: #fafbfc;">
			`;

			if (hasParameters) {
				html += `<div style="display: grid; gap: 8px;">`;

				parameters.forEach((param) => {
					const pricingIcon = param.pricing_type === 'Percentage' ? 'percent' : 'rupee';
					const pricingValue = param.pricing_type === 'Percentage'
						? `${param.price_percentage || 0}%`
						: `${format_currency(param.price_amount || 0, 'INR')}`;

					html += `
						<div style="background: white; padding: 10px; border-radius: 6px; border: 1px solid #e8ebed; display: grid; grid-template-columns: 2fr 2fr 1.5fr 1.5fr; gap: 10px; align-items: center;">
							<div>
								<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PARAMETER</div>
								<div style="font-size: 12px; font-weight: 700; color: #36414c;">${param.parameter || 'N/A'}</div>
							</div>
							<div>
								<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">VALUE</div>
								<div style="background: #e8f5e9; color: #2e7d32; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
									${param.selected_value || 'N/A'}
								</div>
							</div>
							<div>
								<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">TYPE</div>
								<div style="background: #fff3cd; color: #856404; padding: 4px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; text-align: center;">
									${param.pricing_type || 'N/A'}
								</div>
							</div>
							<div>
								<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PRICE</div>
								<div style="background: #e3f2fd; color: #1976d2; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; text-align: center; display: flex; align-items: center; justify-content: center; gap: 3px;">
									<i class="fa fa-${pricingIcon}" style="font-size: 9px;"></i>
									${pricingValue}
								</div>
							</div>
						</div>
					`;
				});

				html += `</div>`;
			} else {
				html += `
					<div style="text-align: center; padding: 20px; background: white; border-radius: 6px; border: 1px dashed #dee2e6;">
						<i class="fa fa-info-circle" style="font-size: 24px; color: #d1d8dd; margin-bottom: 8px;"></i>
						<p style="color: #6c7680; margin: 0; font-size: 12px;">No parameters</p>
					</div>
				`;
			}

			// Add Edit Discount button
			const hasDiscount = record.apply_discount_after && record.discount_percentage > 0;
			const discountInfo = hasDiscount
				? `${record.discount_percentage}% after ${record.apply_discount_after}`
				: 'No discount';

			html += `
							<div style="padding: 12px; background: #f8f9fa; border-top: 1px solid #e8ebed; display: flex; justify-content: space-between; align-items: center;" onclick="event.stopPropagation();">
								<div style="display: flex; align-items: center; gap: 8px;">
									<i class="fa fa-percent" style="color: #ff9800; font-size: 12px;"></i>
									<span style="font-size: 11px; color: #6c7680; font-weight: 600;">Discount: </span>
									<span style="font-size: 11px; color: #36414c; font-weight: 600;">${discountInfo}</span>
								</div>
								<button class="btn-edit-discount" data-record="${record.name}"
									style="background: #2490ef; color: white; font-weight: 600; padding: 6px 14px; border-radius: 4px; border: none; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s; font-size: 11px;"
									onclick="event.stopPropagation();">
									<i class="fa fa-edit"></i>
									<span>Edit Discount</span>
								</button>
							</div>
						</div>
					</div>
				</div>
			`;
		});

		html += `
				</div>
			</div>

			<style>
				.config-card-advanced:hover {
					box-shadow: 0 4px 12px rgba(0,0,0,0.1) !important;
					transform: translateY(-1px);
				}

				.config-card-advanced.selected {
					border-left: 4px solid #48bb78 !important;
					box-shadow: 0 4px 16px rgba(72, 187, 120, 0.3) !important;
				}

				.config-card-header:hover i.fa-chevron-down {
					color: #667eea !important;
				}

				.config-card-body.expanded {
					max-height: 1000px !important;
				}

				.config-card-header .fa-chevron-down {
					transition: transform 0.2s ease;
				}

				.config-card-body.expanded ~ .config-card-header .fa-chevron-down {
					transform: rotate(180deg);
				}

				.info-card-compact:hover {
					transform: translateY(-1px);
					box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
				}
			</style>
		`;

		dialog.fields_dict.dialog_container.$wrapper.html(html);

		// Attach event listener to radio buttons
		setTimeout(() => {
			const $selectBtn = dialog.$wrapper.find('.btn-select-config');

			dialog.$wrapper.find('.config-radio').on('change', function() {
				const selectedValue = $(this).val();

				// Remove selected class from all cards
				dialog.$wrapper.find('.config-card-advanced').removeClass('selected');

				// Add selected class to the selected card
				$(this).closest('.config-card-advanced').addClass('selected');

				// Show Select button
				$selectBtn.css('display', 'flex');
				$selectBtn.data('selected-record', selectedValue);
			});

			// Attach event listener to "Select" button
			$selectBtn.on('click', function() {
				const selectedRecord = $(this).data('selected-record');
				if (selectedRecord) {
					ujwal_industries.grid_custom_icons.handle_config_selection(dialog, selectedRecord);
				}
			});

			// Attach event listener to "Create New" button
			const createBtn = dialog.$wrapper.find('.btn-create-new-config');
			if (createBtn.length) {
				createBtn.on('click', function() {
					const base_item = $(this).data('base-item');
					ujwal_industries.grid_custom_icons.create_new_non_standard_item(base_item, dialog);
				});

				// Add hover effect
				createBtn.on('mouseenter', function() {
					$(this).css({
						'background': '#667eea',
						'color': 'white',
						'transform': 'translateY(-1px)',
						'box-shadow': '0 4px 12px rgba(102, 126, 234, 0.3)'
					});
				}).on('mouseleave', function() {
					$(this).css({
						'background': 'white',
						'color': '#667eea',
						'transform': 'translateY(0)',
						'box-shadow': 'none'
					});
				});
			}

			// Attach event listener to "Edit Discount" buttons
			const editDiscountBtns = dialog.$wrapper.find('.btn-edit-discount');
			editDiscountBtns.each(function() {
				$(this).on('click', function(e) {
					e.stopPropagation();
					e.preventDefault();
					const record_name = $(this).data('record');
					ujwal_industries.grid_custom_icons.show_edit_discount_dialog(record_name, dialog);
				});

				// Add hover effect
				$(this).on('mouseenter', function() {
					$(this).css({
						'background': '#1976d2',
						'transform': 'translateY(-1px)',
						'box-shadow': '0 4px 12px rgba(36, 144, 239, 0.3)'
					});
				}).on('mouseleave', function() {
					$(this).css({
						'background': '#2490ef',
						'transform': 'translateY(0)',
						'box-shadow': 'none'
					});
				});
			});
		}, 100);
	},

	show_edit_discount_dialog: function(record_name, parent_dialog) {
		// Fetch the record
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'Non Standard Item Creation',
				name: record_name
			},
			callback: function(r) {
				if (r.message) {
					const record = r.message;
					ujwal_industries.grid_custom_icons.open_discount_edit_dialog(record, parent_dialog);
				}
			}
		});
	},

	open_discount_edit_dialog: function(record, parent_dialog) {
		// First, fetch the latest price log
		const parent_doctype = parent_dialog.parent_frm ? parent_dialog.parent_frm.doctype : null;

		let filters = {
			non_standard_item: record.name
		};
		if (parent_doctype) {
			filters.reference_doctype = parent_doctype;
		}

		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Price Log Entry',
				filters: filters,
				fields: ['discount_parameter', 'discount_percentage', 'final_price', 'created_on', 'reference_doctype', 'reference_name'],
				order_by: 'created_on desc',
				limit: 1
			},
			callback: function(r) {
				let latest_discount_after = record.apply_discount_after || '';
				let latest_discount_percentage = record.discount_percentage || 0;
				let latest_final_price = record.valuation_price;
				let log_source = '';

				if (r.message && r.message.length > 0) {
					const latest_log = r.message[0];
					latest_discount_after = latest_log.discount_parameter || '';
					latest_discount_percentage = latest_log.discount_percentage || 0;
					latest_final_price = latest_log.final_price || record.valuation_price;

					if (latest_log.reference_doctype && latest_log.reference_name) {
						log_source = `${latest_log.reference_doctype}: ${latest_log.reference_name}`;
					}
				}

				// Build the discount info HTML
				const discountInfoHtml = log_source ? `<div style="font-size: 11px; color: #6c7680; margin-bottom: 10px; padding: 8px; background: #e8f5e9; border-radius: 4px;"><i class="fa fa-info-circle" style="color: #48bb78;"></i> Last used in: <strong>${log_source}</strong></div>` : '';
				const previouslyUsedBadge = latest_discount_percentage > 0 ? '<span style="background: #48bb78; color: white; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-left: 10px;">PREVIOUSLY USED</span>' : '';

				const editDialog = new frappe.ui.Dialog({
					title: __('Edit Discount - {0}', [record.new_item_code]),
					fields: [
						{
							fieldname: 'info_html',
							fieldtype: 'HTML',
							options: `
								<div style="background: #fff3e0; padding: 12px; border-radius: 6px; margin-bottom: 15px; border-left: 3px solid #ff9800;">
									<div style="font-size: 12px; font-weight: 600; color: #36414c; margin-bottom: 8px;">
										<i class="fa fa-percent" style="color: #ff9800;"></i> Discount Information${previouslyUsedBadge}
									</div>
									${discountInfoHtml}
								</div>
							`
						},
						{
							fieldname: 'apply_discount_after',
							label: __('Apply Discount After'),
							fieldtype: 'Select',
							options: record.brand === 'Siemens' ? 'Absolute Amount' : '\nPercentage Values',
							default: record.brand === 'Siemens' ? 'Absolute Amount' : (latest_discount_after || 'Percentage Values')
						},
						{
							fieldname: 'discount_percentage',
							label: __('Discount Percentage (%)'),
							fieldtype: 'Float',
							default: latest_discount_percentage,
							depends_on: 'apply_discount_after'
						},
						{
							fieldname: 'section_break',
							fieldtype: 'Section Break'
						},
						{
							fieldname: 'current_info',
							fieldtype: 'HTML',
							options: `
								<div style="background: #f8f9fa; padding: 12px; border-radius: 6px; margin-bottom: 10px;">
									<div style="font-size: 11px; color: #6c7680; margin-bottom: 8px; font-weight: 600;">CURRENT VALUES</div>
									<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
										<div>
											<div style="font-size: 10px; color: #6c7680;">Valuation Price</div>
											<div style="font-size: 14px; font-weight: 600; color: #36414c;">${format_currency(record.valuation_price || 0, 'INR')}</div>
										</div>
										<div>
											<div style="font-size: 10px; color: #6c7680;">Final Price (With Discount)</div>
											<div style="font-size: 14px; font-weight: 600; color: #48bb78;">${format_currency(latest_final_price, 'INR')}</div>
										</div>
									</div>
								</div>
							`
						}
					],
					primary_action_label: latest_discount_percentage > 0 ? __('Apply New Discount') : __('Apply Discount'),
					primary_action: function(values) {
						ujwal_industries.grid_custom_icons.update_discount(record, values, editDialog, parent_dialog, true, latest_discount_after, latest_discount_percentage);
					},
					secondary_action_label: latest_discount_percentage > 0 ? __('Use Existing & Add Item') : null,
					secondary_action: latest_discount_percentage > 0 ? function() {
						// Add item to grid directly with existing discount
						ujwal_industries.grid_custom_icons.add_item_from_step2(record, latest_final_price, parent_dialog);
						editDialog.hide();
					} : null
				});

				// Store original values for comparison
				editDialog.original_discount_after = latest_discount_after;
				editDialog.original_discount_percentage = latest_discount_percentage;
				editDialog.original_final_price = latest_final_price;
				editDialog.record = record;
				editDialog.parent_dialog = parent_dialog;

				editDialog.show();
			}
		});
	},

	add_item_from_step2: function(record, final_price, parent_dialog) {
		// Add item to grid directly from Step 2 without creating new log entry
		const new_item_code = record.new_item_code;
		const frm = parent_dialog.parent_frm;
		const original_row = parent_dialog.original_row;

		if (frm && original_row && new_item_code) {
			frappe.show_alert({
				message: __('Adding item with existing discount: {0}', [format_currency(final_price, 'INR')]),
				indicator: 'blue'
			}, 5);

			// First set the item_code - this will trigger item details fetch
			frappe.model.set_value(original_row.doctype, original_row.name, 'item_code', new_item_code).then(() => {
				// After item details are fetched, override the rate with our discounted price
				setTimeout(() => {
					frappe.model.set_value(original_row.doctype, original_row.name, 'rate', final_price);
					frappe.model.set_value(original_row.doctype, original_row.name, 'qty', 1);

					// Refresh the grid to show the new values
					frm.fields_dict.sub_assembly_items.grid.refresh();
					frm.refresh_field('sub_assembly_items');


					frm.fields_dict.po_items.grid.refresh();
					frm.refresh_field('po_items');
				}, 500);
			});

			parent_dialog.hide();
		}
	},

	update_discount: function(record, values, editDialog, parent_dialog, force_new_log, original_discount_after, original_discount_percentage) {
		// Check if discount values have actually changed
		const discount_changed = force_new_log ||
			(values.apply_discount_after !== original_discount_after) ||
			(values.discount_percentage !== original_discount_percentage);

		if (!discount_changed) {
			// Values haven't changed, just add item directly if we're in the right context
			const final_price = editDialog.original_final_price;
			ujwal_industries.grid_custom_icons.add_item_from_step2(record, final_price, parent_dialog);
			editDialog.hide();
			return;
		}

		// Call server method to update discount and create log
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.non_standard_item_creation.non_standard_item_creation.update_discount',
			args: {
				docname: record.name,
				apply_discount_after: values.apply_discount_after || null,
				discount_percentage: values.discount_percentage || 0,
				reference_doctype: parent_dialog.parent_frm ? parent_dialog.parent_frm.doctype : null,
				reference_name: parent_dialog.parent_frm ? parent_dialog.parent_frm.doc.name : null
			},
			callback: function(r) {
				if (r.message && r.message.success) {
					const final_price = r.message.new_price;

					frappe.show_alert({
						message: __('Discount applied successfully. Final price: {0}', [format_currency(final_price, 'INR')]),
						indicator: 'green'
					}, 5);

					// Add item to grid
					ujwal_industries.grid_custom_icons.add_item_from_step2(record, final_price, parent_dialog);
					editDialog.hide();
				}
			},
			error: function(err) {
				frappe.msgprint(__('Error updating discount: {0}', [err.message || err]));
			}
		});
	},

	handle_config_selection: function(dialog, selected_record_name) {
		// Fetch the selected record
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'Non Standard Item Creation',
				name: selected_record_name
			},
			callback: function(r) {
				if (r.message) {
					ujwal_industries.grid_custom_icons.show_selected_config_discount_step(dialog, r.message);
				}
			}
		});
	},

	show_selected_config_discount_step: function(dialog, selected_config) {
		// Show step with selected config parameters and discount input
		dialog.current_step = 3;

		// Update buttons - will be set in render_discount_step
		dialog.$wrapper.find('.btn-modal-secondary').show();

		// Fetch latest price log for this non-standard item
		const parent_doctype = dialog.parent_frm ? dialog.parent_frm.doctype : null;

		// Show loading state first
		dialog.fields_dict.dialog_container.$wrapper.html(`
			${ujwal_industries.grid_custom_icons.get_stepper_html_3step(3, 100)}
			<div class="text-center" style="padding: 40px;">
				<i class="fa fa-spinner fa-spin fa-2x text-muted"></i>
				<p class="text-muted" style="margin-top: 10px; font-size: 13px;">Loading discount information...</p>
			</div>
		`);

		// Build filters - filter by non_standard_item and parent doctype (NOT specific document name)
		let filters = {
			non_standard_item: selected_config.name
		};

		if (parent_doctype) {
			filters.reference_doctype = parent_doctype;
		}

		// Fetch latest price log
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Price Log Entry',
				filters: filters,
				fields: ['discount_parameter', 'discount_percentage', 'final_price', 'created_on', 'reference_doctype', 'reference_name'],
				order_by: 'created_on desc',
				limit: 1
			},
			callback: function(r) {
				let latest_discount_after = selected_config.apply_discount_after || '';
				let latest_discount_percentage = 0;
				let latest_final_price = selected_config.valuation_price;
				let log_source = '';

				// If we found a price log, use those values
				if (r.message && r.message.length > 0) {
					const latest_log = r.message[0];
					latest_discount_after = latest_log.discount_parameter || '';
					latest_discount_percentage = latest_log.discount_percentage || 0;
					latest_final_price = latest_log.final_price || selected_config.valuation_price;

					// Track where this log came from
					if (latest_log.reference_doctype && latest_log.reference_name) {
						log_source = `${latest_log.reference_doctype}: ${latest_log.reference_name}`;
					}
				}

				// Store these values in dialog for easy access
				dialog.latest_discount_after = latest_discount_after;
				dialog.latest_discount_percentage = latest_discount_percentage;
				dialog.latest_final_price = latest_final_price;
				dialog.log_source = log_source;

				// Now render the actual form with pre-filled values
				ujwal_industries.grid_custom_icons.render_discount_step(dialog, selected_config, latest_discount_after, latest_discount_percentage, latest_final_price, log_source);
			}
		});
	},

	render_discount_step: function(dialog, selected_config, discount_after, discount_percentage, final_price, log_source) {

		const parameters = selected_config.parameters || [];
		let parametersHtml = '';

		if (parameters.length > 0) {
			parametersHtml = '<div style="margin-bottom: 20px;"><div style="font-size: 13px; font-weight: 700; color: #36414c; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;"><i class="fa fa-sliders" style="color: #667eea;"></i><span>Configuration Parameters</span></div><div style="display: grid; gap: 8px;">';

			parameters.forEach(param => {
				const pricingValue = param.pricing_type === 'Percentage'
					? `${param.price_percentage || 0}%`
					: (param.pricing_type === 'Fixed Amount' ? format_currency(param.price_amount || 0, 'INR') : 'Both');

				parametersHtml += `
					<div style="background: #f8f9fa; padding: 12px; border-radius: 6px; border: 1px solid #e8ebed; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; align-items: center;">
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PARAMETER</div>
							<div style="font-size: 12px; font-weight: 700; color: #36414c;">${param.parameter}</div>
						</div>
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">VALUE</div>
							<div style="background: #e8f5e9; color: #2e7d32; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
								${param.selected_value}
							</div>
						</div>
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PRICE</div>
							<div style="background: #e3f2fd; color: #1976d2; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
								${pricingValue}
							</div>
						</div>
					</div>
				`;
			});
			parametersHtml += '</div></div>';
		}

		const html = `
			${ujwal_industries.grid_custom_icons.get_stepper_html_3step(3, 100)}
			<div class="selected-config-discount" style="padding: 20px; background: #ffffff;">
				<!-- Header -->
				<div style="background: linear-gradient(135deg, #48bb78 0%, #2e7d32 100%); padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; color: white;">
					<div style="display: flex; justify-content: space-between; align-items: center;">
						<div>
							<div style="font-size: 11px; opacity: 0.9; margin-bottom: 4px;">SELECTED CONFIGURATION</div>
							<div style="font-size: 16px; font-weight: 700;">${selected_config.new_item_code}</div>
							<div style="font-size: 12px; opacity: 0.8; margin-top: 2px;">${selected_config.brand} • Frame: ${selected_config.frame_size || 'N/A'}</div>
						</div>
						<div style="text-align: right;">
							<div style="font-size: 11px; opacity: 0.9;">VALUATION PRICE</div>
							<div style="font-size: 20px; font-weight: 800;">${format_currency(selected_config.valuation_price || 0, 'INR')}</div>
						</div>
					</div>
				</div>

				${parametersHtml}

				<!-- Discount Section -->
				<div style="background: #fff3e0; padding: 15px; border-radius: 8px; border-left: 3px solid #ff9800; margin-bottom: 15px;">
					<div style="font-size: 13px; font-weight: 700; color: #36414c; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
						<i class="fa fa-percent" style="color: #ff9800;"></i>
						<span>Apply Discount</span>
						${discount_percentage > 0 ? '<span style="background: #48bb78; color: white; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-left: auto;">PREVIOUSLY USED</span>' : ''}
					</div>
					${log_source ? `<div style="font-size: 11px; color: #6c7680; margin-bottom: 10px; padding: 8px; background: #e8f5e9; border-radius: 4px;"><i class="fa fa-info-circle" style="color: #48bb78;"></i> Last used in: <strong>${log_source}</strong></div>` : ''}
					<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; align-items: center;">
						<div>
							<label style="font-size: 11px; color: #6c7680; margin-bottom: 4px; display: block; font-weight: 600;">Apply Discount After</label>
							<select class="discount-after-select" style="width: 100%; padding: 8px 12px; border: 1px solid #d1d8dd; border-radius: 6px; font-size: 13px; background: white;">
								${selected_config.brand === 'Siemens' ? `
									<option value="Absolute Amount" selected>Absolute Amount</option>
								` : `
									<option value="">-- No Discount --</option>
									<option value="Percentage Values" ${discount_after === 'Percentage Values' ? 'selected' : ''}>Percentage Values</option>
								`}
							</select>
						</div>
						<div>
							<label style="font-size: 11px; color: #6c7680; margin-bottom: 4px; display: block; font-weight: 600;">Discount Percentage (%)</label>
							<input type="number" class="discount-percentage-input" min="0" max="100" step="0.01" placeholder="0" value="${discount_percentage}" style="width: 100%; padding: 8px 12px; border: 1px solid #d1d8dd; border-radius: 6px; font-size: 13px; background: white;" />
						</div>
					</div>
				</div>

				<!-- Final Price Display -->
				<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px 20px; border-radius: 8px; color: white;">
					<div style="display: flex; justify-content: space-between; align-items: center;">
						<div>
							<div style="font-size: 11px; opacity: 0.9; margin-bottom: 4px;">FINAL PRICE (WITH DISCOUNT)</div>
							<div style="font-size: 14px; font-weight: 600; opacity: 0.9;">This price will be added to your ${dialog.parent_frm ? dialog.parent_frm.doctype : 'document'}</div>
						</div>
						<div style="text-align: right;">
							<div style="font-size: 24px; font-weight: 800;">${format_currency(final_price, 'INR')}</div>
						</div>
					</div>
				</div>
			</div>
		`;

		dialog.fields_dict.dialog_container.$wrapper.html(html);
		dialog.selected_config = selected_config;

		// Store original values for comparison
		dialog.original_discount_after = discount_after;
		dialog.original_discount_percentage = discount_percentage;
		dialog.original_final_price = final_price;

		// Set up buttons based on whether there's existing discount
		if (discount_percentage > 0) {
			// Add secondary button to use existing discount
			dialog.set_primary_action(__('Apply New Discount'), function() {
				ujwal_industries.grid_custom_icons.apply_discount_to_selected(dialog, selected_config, true);
			});

			// Add secondary button for using existing discount
			dialog.set_secondary_action_label(__('Add Item (Use Existing)'));
			dialog.set_secondary_action(function() {
				ujwal_industries.grid_custom_icons.add_item_to_grid_directly(selected_config, final_price, dialog, dialog.parent_frm);
			});
		} else {
			// No existing discount, just show apply button
			dialog.set_primary_action(__('Apply Discount'), function() {
				ujwal_industries.grid_custom_icons.apply_discount_to_selected(dialog, selected_config, false);
			});
		}
	},

	apply_discount_to_selected: function(dialog, selected_config, force_new_log) {
		const apply_discount_after = dialog.$wrapper.find('.discount-after-select').val();
		const discount_percentage = parseFloat(dialog.$wrapper.find('.discount-percentage-input').val()) || 0;

		// Check if discount values have actually changed
		const discount_changed = force_new_log ||
			(apply_discount_after !== dialog.original_discount_after) ||
			(discount_percentage !== dialog.original_discount_percentage);

		if (!discount_changed) {
			// Values haven't changed, just add item directly
			const final_price = dialog.original_final_price;
			ujwal_industries.grid_custom_icons.add_item_to_grid_directly(selected_config, final_price, dialog, dialog.parent_frm);
			return;
		}

		// Call the update_discount method to create new log entry
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.non_standard_item_creation.non_standard_item_creation.update_discount',
			args: {
				docname: selected_config.name,
				apply_discount_after: apply_discount_after || null,
				discount_percentage: discount_percentage,
				reference_doctype: dialog.parent_frm ? dialog.parent_frm.doctype : null,
				reference_name: dialog.parent_frm ? dialog.parent_frm.doc.name : null
			},
			callback: function(r) {
				if (r.message && r.message.success) {
					const final_price = r.message.new_price;
					const new_item_code = selected_config.new_item_code;

					frappe.show_alert({
						message: __('Discount applied successfully. Final price: {0}', [format_currency(final_price, 'INR')]),
						indicator: 'green'
					}, 5);

					// Add the non-standard item to the items child table
					if (dialog.parent_frm && dialog.original_row) {
						const frm = dialog.parent_frm;
						const original_row = dialog.original_row;

						// First set the item_code - this will trigger item details fetch
						frappe.model.set_value(original_row.doctype, original_row.name, 'item_code', new_item_code).then(() => {
							// After item details are fetched, override the rate with our discounted price
							setTimeout(() => {
								frappe.model.set_value(original_row.doctype, original_row.name, 'rate', final_price);
								frappe.model.set_value(original_row.doctype, original_row.name, 'qty', 1);

								// Refresh the grid to show the new values
								frm.fields_dict.sub_assembly_items.grid.refresh();
								frm.refresh_field('sub_assembly_items');
								
								
								frm.fields_dict.po_items.grid.refresh();
								frm.refresh_field('po_items');
							}, 500);
						});
					}

					dialog.hide();
				}
			},
			error: function(err) {
				frappe.msgprint(__('Error applying discount: {0}', [err.message || err]));
			}
		});
	},

	create_new_non_standard_item: function(base_item_code, parent_dialog) {
		// Transition to Step 3 - Creation Form
		this.show_step_3(parent_dialog, base_item_code);
	},

	show_step_3: function(dialog, base_item_code) {
		dialog.current_step = 3;

		// Update buttons
		dialog.set_primary_action(__('Save & Submit'), function() {
			ujwal_industries.grid_custom_icons.save_non_standard_item(dialog);
		});
		dialog.$wrapper.find('.btn-modal-secondary').show();

		// Show loading state
		const loadingHtml = `
			${ujwal_industries.grid_custom_icons.get_stepper_html_3step(3, 100)}
			<div class="text-center" style="padding: 40px;">
				<i class="fa fa-spinner fa-spin fa-2x text-muted"></i>
				<p class="text-muted" style="margin-top: 10px; font-size: 13px;">Loading configuration form...</p>
			</div>
		`;
		dialog.fields_dict.dialog_container.$wrapper.html(loadingHtml);

		// Fetch item details and brand configuration
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'Item',
				name: base_item_code
			},
			callback: function(r) {
				if (r.message) {
					const item = r.message;
					dialog.creation_item = item;

					// Fetch brand configuration
					ujwal_industries.grid_custom_icons.load_brand_config_for_creation(dialog, item);
				} else {
					frappe.msgprint(__('Error loading item details'));
					ujwal_industries.grid_custom_icons.show_step_2(dialog, base_item_code);
				}
			}
		});
	},

	load_brand_config_for_creation: function(dialog, item) {
		// First, find the Brand Motor Configuration name
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Brand Motor Configuration',
				filters: {
					brand: item.brand,
					is_active: 1
				},
				fields: ['name'],
				limit: 1
			},
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					const config_name = r.message[0].name;

					// Now fetch the full document with child table
					frappe.call({
						method: 'frappe.client.get',
						args: {
							doctype: 'Brand Motor Configuration',
							name: config_name
						},
						callback: function(r2) {
							if (r2.message) {
								const brand_config = r2.message;

								try {
									dialog.brand_values = JSON.parse(brand_config.values_json || '{}');
								} catch(e) {
									dialog.brand_values = {};
								}

								// Get parameters from child table
								dialog.param_configs = brand_config.parameters || [];

								// Fetch base price
								frappe.call({
									method: 'frappe.client.get_list',
									args: {
										doctype: 'Item Price',
										filters: {
											item_code : item.name,
											brand: item.brand
										},
										fields: ['price_list_rate', 'price_list'],
										limit: 1
									},
									callback: function(r3) {
										dialog.base_price = (r3.message && r3.message.length > 0) ? r3.message[0].price_list_rate : 0;

										// Render Step 3 form
										ujwal_industries.grid_custom_icons.render_step_3_form(dialog);
									}
								});
							} else {
								frappe.msgprint(__('Error loading Brand Motor Configuration'));
								ujwal_industries.grid_custom_icons.show_step_2(dialog, item.name);
							}
						}
					});
				} else {
					frappe.msgprint(__('No active Brand Motor Configuration found for {0}', [item.brand]));
					ujwal_industries.grid_custom_icons.show_step_2(dialog, item.name);
				}
			}
		});
	},

	render_step_3_form: function(dialog) {
		const item = dialog.creation_item;
		const params = dialog.param_configs;
		const brand_values = dialog.brand_values;

		let html = `
			${ujwal_industries.grid_custom_icons.get_stepper_html_3step(3, 100)}
			<div class="non-standard-creation-form" style="padding: 20px; background: #ffffff;">
				<!-- Header with Item Info -->
				<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; color: white;">
					<div style="display: flex; justify-content: space-between; align-items: center;">
						<div>
							<div style="font-size: 11px; opacity: 0.9; margin-bottom: 4px;">CREATING CONFIGURATION FOR</div>
							<div style="font-size: 16px; font-weight: 700;">${item.item_code || item.name}</div>
							<div style="font-size: 12px; opacity: 0.8; margin-top: 2px;">${item.brand} • Frame: ${item.frame_size || 'N/A'} • ${item.is_flameproof ? 'FLP' : 'Non-FLP'}</div>
						</div>
						<div style="text-align: right;">
							<div style="font-size: 11px; opacity: 0.9;">BASE PRICE</div>
							<div style="font-size: 20px; font-weight: 800;">${format_currency(dialog.base_price || 0, 'INR')}</div>
						</div>
					</div>
				</div>

				<!-- Parameters Selection -->
				<div style="max-height: 400px; overflow-y: auto; padding-right: 10px;">
					<div style="margin-bottom: 15px;">
						<div style="font-size: 13px; font-weight: 700; color: #36414c; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
							<i class="fa fa-cogs" style="color: #667eea;"></i>
							<span>Configure Parameters</span>
						</div>
		`;

		// Render parameter selection fields
		params.forEach((param, index) => {
			const param_code = param.parameter_code;
			const values_key = param_code + '_values';
			const available_values = brand_values[values_key] || [];

			// Filter values based on motor type and frame size
			let filtered_values = [];
			available_values.forEach(function(val_obj) {
				if (!val_obj.value) return;

				let include = true;

				// Filter by motor type
				if (param.motor_type_dependent && val_obj.motor_type) {
					const expected_type = item.is_flameproof ? 'FLP' : 'Non-FLP';
					if (val_obj.motor_type !== expected_type) {
						include = false;
					}
				}

				// Filter by frame size
				if (param.frame_size_dependent && val_obj.frame_size) {
					if (item.frame_size && val_obj.frame_size != item.frame_size) {
						include = false;
					}
				}

				if (include) {
					filtered_values.push(val_obj);
				}
			});

			html += `
				<div class="parameter-field" data-param="${param.parameter}" data-param-code="${param_code}" data-pricing-type="${param.pricing_type}" style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 12px; border-left: 3px solid #667eea;">
					<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; align-items: center;">
						<div>
							<label style="font-size: 11px; color: #6c7680; margin-bottom: 4px; display: block; font-weight: 600;">${param.parameter}</label>
							<select class="param-select" data-index="${index}" style="width: 100%; padding: 8px 12px; border: 1px solid #d1d8dd; border-radius: 6px; font-size: 13px; background: white;">
								<option value="">Select ${param.parameter}</option>
								${filtered_values.map(v => `<option value="${v.value}" data-price="${v.price || 0}" data-price-pct="${v.price_pct || 0}" data-price-amt="${v.price_amt || 0}">${v.value}</option>`).join('')}
							</select>
						</div>
						<div class="pricing-display" style="text-align: right; opacity: 0.5;">
							<div style="font-size: 10px; color: #6c7680; margin-bottom: 2px;">PRICE IMPACT</div>
							<div class="price-impact" style="font-size: 14px; font-weight: 700; color: #48bb78;">--</div>
						</div>
					</div>
				</div>
			`;
		});

		html += `
					</div>

					<!-- Discount Section -->
					<div style="margin-top: 20px; padding-top: 20px; border-top: 2px dashed #e8ebed;">
						<div style="font-size: 13px; font-weight: 700; color: #36414c; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
							<i class="fa fa-percent" style="color: #ff9800;"></i>
							<span>Apply Discount (Optional)</span>
						</div>

						<div style="background: #fff3e0; padding: 15px; border-radius: 8px; border-left: 3px solid #ff9800;">
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; align-items: center;">
								<div>
									<label style="font-size: 11px; color: #6c7680; margin-bottom: 4px; display: block; font-weight: 600;">Apply Discount After</label>
									<select class="discount-param-select" style="width: 100%; padding: 8px 12px; border: 1px solid #d1d8dd; border-radius: 6px; font-size: 13px; background: white;">
										${item.brand === 'Siemens' ? `
											<option value="Absolute Amount" selected>Absolute Amount</option>
										` : `
											<option value="">-- No Discount --</option>
											<option value="Percentage Values">Percentage Values</option>
										`}
									</select>
								</div>
								<div>
									<label style="font-size: 11px; color: #6c7680; margin-bottom: 4px; display: block; font-weight: 600;">Discount Percentage (%)</label>
									<input type="number" class="discount-percentage-input" min="0" max="100" step="0.01" placeholder="0" disabled style="width: 100%; padding: 8px 12px; border: 1px solid #d1d8dd; border-radius: 6px; font-size: 13px; background: #f5f5f5;" />
								</div>
							</div>
							<div class="discount-display" style="margin-top: 12px; text-align: center; opacity: 0; transition: opacity 0.3s;">
								<div style="margin-bottom: 8px;">
									<div style="font-size: 10px; color: #ff9800; margin-bottom: 2px;">DISCOUNT AMOUNT</div>
									<div class="discount-amount" style="font-size: 16px; font-weight: 700; color: #ff9800;">--</div>
								</div>
								<div>
									<div style="font-size: 10px; color: #48bb78; margin-bottom: 2px;">FINAL NS PRICE</div>
									<div class="final-price" style="font-size: 16px; font-weight: 700; color: #48bb78;">--</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Summary Footer -->
			<div style="background: #f8f9fa; padding: 15px 20px; border-top: 2px solid #e8ebed;">
				<div style="display: flex; justify-content: space-between; align-items: center;">
					<div>
						<div style="font-size: 11px; color: #6c7680; margin-bottom: 4px;">NEW ITEM CODE</div>
						<div class="new-item-code-preview" style="font-size: 13px; font-weight: 700; color: #36414c; font-family: monospace;">${item.item_code || item.name}</div>
					</div>
					<div style="text-align: right;">
						<div style="font-size: 11px; color: #6c7680; margin-bottom: 4px;">ZD NS PRICE( Zero discount non standard price )</div>
						<div class="computed-price-preview" style="font-size: 20px; font-weight: 800; color: #48bb78;">${format_currency(dialog.base_price || 0, 'INR')}</div>
					</div>
				</div>
			</div>

			<style>
				.param-select:focus {
					outline: none;
					border-color: #667eea;
					box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
				}
			</style>
		`;

		dialog.fields_dict.dialog_container.$wrapper.html(html);

		// Initialize parameter selection handlers
		dialog.selected_parameters = [];
		dialog.apply_discount_after = null;
		dialog.discount_percentage = 0;

		dialog.$wrapper.find('.param-select').on('change', function() {
			ujwal_industries.grid_custom_icons.handle_parameter_change(dialog, $(this));
		});

		// Discount parameter dropdown handler
		dialog.$wrapper.find('.discount-param-select').on('change', function() {
			const selected_value = $(this).val();
			dialog.apply_discount_after = selected_value || null;

			// Enable/disable discount percentage input
			const $discountInput = dialog.$wrapper.find('.discount-percentage-input');
			if (selected_value) {
				$discountInput.prop('disabled', false).css('background', 'white');
			} else {
				$discountInput.prop('disabled', true).val('').css('background', '#f5f5f5');
				dialog.discount_percentage = 0;
				dialog.$wrapper.find('.discount-display').css('opacity', '0');
			}

			ujwal_industries.grid_custom_icons.update_creation_summary(dialog);
		});

		// Discount percentage input handler
		dialog.$wrapper.find('.discount-percentage-input').on('input', function() {
			dialog.discount_percentage = parseFloat($(this).val()) || 0;
			ujwal_industries.grid_custom_icons.update_creation_summary(dialog);
		});

		// Add focus styling
		dialog.$wrapper.find('.discount-param-select, .discount-percentage-input').on('focus', function() {
			$(this).css({
				'outline': 'none',
				'border-color': '#ff9800',
				'box-shadow': '0 0 0 3px rgba(255, 152, 0, 0.1)'
			});
		}).on('blur', function() {
			$(this).css({
				'border-color': '#d1d8dd',
				'box-shadow': 'none'
			});
		});
	},

	handle_parameter_change: function(dialog, $select) {
		const selected_value = $select.val();
		const $option = $select.find('option:selected');
		const $field = $select.closest('.parameter-field');
		const param_name = $field.data('param');
		const param_code = $field.data('param-code');
		const pricing_type = $field.data('pricing-type');

		if (!selected_value) {
			// Remove parameter if deselected
			dialog.selected_parameters = dialog.selected_parameters.filter(p => p.param_code !== param_code);
			$field.find('.pricing-display').css('opacity', '0.5');
			$field.find('.price-impact').text('--');
		} else {
			// Add/update parameter
			const param_data = {
				parameter: param_name,
				param_code: param_code,
				selected_value: selected_value,
				pricing_type: pricing_type,
				price: parseFloat($option.data('price') || 0),
				price_pct: parseFloat($option.data('price-pct') || 0),
				price_amt: parseFloat($option.data('price-amt') || 0)
			};

			// Remove existing entry for this param
			dialog.selected_parameters = dialog.selected_parameters.filter(p => p.param_code !== param_code);
			dialog.selected_parameters.push(param_data);

			// Update pricing display
			let price_impact = 0;
			if (pricing_type === 'Percentage') {
				price_impact = (dialog.base_price * param_data.price) / 100;
				$field.find('.price-impact').html(`+${param_data.price}% <span style="font-size: 11px;">(${format_currency(price_impact, 'INR')})</span>`);
			} else if (pricing_type === 'Fixed Amount') {
				price_impact = param_data.price;
				$field.find('.price-impact').text(`+${format_currency(price_impact, 'INR')}`);
			} else if (pricing_type === 'Both') {
				const pct_impact = (dialog.base_price * param_data.price_pct) / 100;
				price_impact = pct_impact + param_data.price_amt;
				$field.find('.price-impact').html(`+${param_data.price_pct}% + ${format_currency(param_data.price_amt, 'INR')}`);
			}

			$field.find('.pricing-display').css('opacity', '1');
		}

		// Recalculate total price and item code
		ujwal_industries.grid_custom_icons.update_creation_summary(dialog);
	},

	update_creation_summary: function(dialog) {
		const item = dialog.creation_item;
		let base_price = dialog.base_price;
		let item_code_parts = [item.item_code || item.name];

		// Separate percentage and absolute parameters
		const percentage_params = dialog.selected_parameters.filter(p => p.pricing_type === 'Percentage');
		const absolute_params = dialog.selected_parameters.filter(p => p.pricing_type === 'Fixed Amount' || p.pricing_type === 'Both');

		// Calculate valuation price (always without discount)
		let valuation_price = base_price;

		// Add all percentage parameters
		percentage_params.forEach(param => {
			const increment = (base_price * param.price) / 100;
			valuation_price += increment;
			item_code_parts.push(`${param.param_code}-${param.selected_value}`);
		});

		// Add all absolute parameters
		absolute_params.forEach(param => {
			let increment = 0;
			if (param.pricing_type === 'Fixed Amount') {
				increment = param.price;
			} else if (param.pricing_type === 'Both') {
				increment = (base_price * param.price_pct) / 100 + param.price_amt;
			}
			valuation_price += increment;
			item_code_parts.push(`${param.param_code}-${param.selected_value}`);
		});

		valuation_price = Math.round(valuation_price * 100) / 100;
		const new_item_code = item_code_parts.join('_');

		// Calculate final price with discount (for display only)
		let final_price = valuation_price;
		let discount_amount = 0;

		if (dialog.apply_discount_after && dialog.discount_percentage > 0) {
			let running_total = base_price;

			// Add percentage parameters
			percentage_params.forEach(param => {
				const increment = (base_price * param.price) / 100;
				running_total += increment;
			});

			if (dialog.apply_discount_after === 'Percentage Values') {
				// Apply discount after percentage params, before absolute params
				discount_amount = (running_total * dialog.discount_percentage) / 100;
				final_price = running_total - discount_amount;
				// Add absolute params after discount
				absolute_params.forEach(param => {
					let increment = 0;
					if (param.pricing_type === 'Fixed Amount') {
						increment = param.price;
					} else if (param.pricing_type === 'Both') {
						increment = (base_price * param.price_pct) / 100 + param.price_amt;
					}
					final_price += increment;
				});
			} else if (dialog.apply_discount_after === 'Absolute Amount') {
				// Add absolute params first, then apply discount
				absolute_params.forEach(param => {
					let increment = 0;
					if (param.pricing_type === 'Fixed Amount') {
						increment = param.price;
					} else if (param.pricing_type === 'Both') {
						increment = (base_price * param.price_pct) / 100 + param.price_amt;
					}
					running_total += increment;
				});
				// Apply discount on total
				discount_amount = (running_total * dialog.discount_percentage) / 100;
				final_price = running_total - discount_amount;
			}

			final_price = Math.round(final_price * 100) / 100;

			dialog.$wrapper.find('.discount-display').css('opacity', '1');
			dialog.$wrapper.find('.discount-amount').text(`${format_currency(discount_amount, 'INR')} (${dialog.discount_percentage}%)`);
			dialog.$wrapper.find('.final-price').text(`${format_currency(final_price, 'INR')}`);
		} else {
			dialog.$wrapper.find('.discount-display').css('opacity', '0');
		}

		dialog.$wrapper.find('.new-item-code-preview').text(new_item_code);
		dialog.$wrapper.find('.computed-price-preview').text(format_currency(valuation_price, 'INR'));

		// Store for saving (valuation_price is the master price without discount)
		dialog.new_item_code = new_item_code;
		dialog.valuation_price = valuation_price;
		dialog.final_price_with_discount = final_price;  // For price log
	},

	save_non_standard_item: function(dialog) {
		if (!dialog.selected_parameters || dialog.selected_parameters.length === 0) {
			frappe.msgprint(__('Please select at least one parameter'));
			return;
		}

		// Show saving indicator
		dialog.get_primary_btn().prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Saving...');

		// Prepare parameters data
		const parameters = dialog.selected_parameters.map(p => ({
			parameter: p.parameter,
			parameter_code: p.param_code,
			selected_value: p.selected_value,
			pricing_type: p.pricing_type,
			price_percentage: p.pricing_type === 'Percentage' ? p.price : (p.pricing_type === 'Both' ? p.price_pct : null),
			price_amount: p.pricing_type === 'Fixed Amount' ? p.price : (p.pricing_type === 'Both' ? p.price_amt : null)
		}));

		const item = dialog.creation_item;

		// Prepare price log entry
		const price_log = {
			reference_doctype: dialog.parent_frm ? dialog.parent_frm.doctype : null,
			reference_name: dialog.parent_frm ? dialog.parent_frm.doc.name : null,
			created_by: frappe.session.user,
			created_on: frappe.datetime.now_datetime(),
			discount_parameter: dialog.apply_discount_after || null,
			discount_percentage: dialog.discount_percentage || 0,
			valuation_price: dialog.valuation_price,
			final_price: dialog.final_price_with_discount || dialog.valuation_price
		};

		// Prepare document data
		const doc_data = {
			base_item: item.name,
			brand: item.brand,
			item_group: item.item_group,
			frame_size: item.frame_size,
			is_flameproof_flp: item.is_flameproof || 0,
			base_price: dialog.base_price,
			apply_discount_after: dialog.apply_discount_after || null,
			discount_percentage: 0,
			parameters: parameters,
			price_logs: [price_log]
		};

		// Create and submit Non Standard Item Creation document using custom method
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.non_standard_item_creation.non_standard_item_creation.create_from_dialog',
			args: {
				doc_data: doc_data
			},
			callback: function(r) {
				if (r.message) {
					const created_doc = r.message;
					const final_price = dialog.final_price_with_discount || dialog.valuation_price;
					const new_item_code = created_doc.new_item_code;

					frappe.show_alert({
						message: __('Non-Standard Item Created: {0} - Price: {1}', [new_item_code, format_currency(final_price, 'INR')]),
						indicator: 'green'
					}, 5);

					// Add the newly created non-standard item to the items child table
					if (dialog.parent_frm && dialog.original_row) {
						const frm = dialog.parent_frm;
						const original_row = dialog.original_row;

						// First set the item_code - this will trigger item details fetch
						frappe.model.set_value(original_row.doctype, original_row.name, 'item_code', new_item_code).then(() => {
							// After item details are fetched, override the rate with our discounted price
							setTimeout(() => {
								frappe.model.set_value(original_row.doctype, original_row.name, 'rate', final_price);
								frappe.model.set_value(original_row.doctype, original_row.name, 'qty', 1);

								// Refresh the grid to show the new values
								frm.fields_dict.sub_assembly_items.grid.refresh();
								frm.refresh_field('sub_assembly_items');
								
								frm.fields_dict.po_items.grid.refresh();
								frm.refresh_field('po_items');
							}, 500);
						});
					}

					// Close the dialog
					dialog.hide();
				}
			},
			error: function(err) {
				frappe.msgprint(__('Error creating document: {0}', [err.message || err]));
				dialog.get_primary_btn().prop('disabled', false).html(__('Save & Submit'));
			}
		});
	},

	get_stepper_html_3step: function(current_step, progress_percent) {
		return `
			<div class="stepper-container">
				<div class="stepper-progress">
					<div class="progress-line" style="width: ${progress_percent}%;"></div>
					<div class="step ${current_step === 1 ? 'active' : 'completed'}">
						<div class="step-circle">
							<span class="step-number">1</span>
						</div>
						<div class="step-label">Item Details</div>
						<div class="step-description">Base Information</div>
					</div>
					<div class="step ${current_step === 2 ? 'active' : (current_step > 2 ? 'completed' : '')}">
						<div class="step-circle">
							<span class="step-number">2</span>
						</div>
						<div class="step-label">Existing Records</div>
						<div class="step-description">Previous Configurations</div>
					</div>
					<div class="step ${current_step === 3 ? 'active' : ''}">
						<div class="step-circle">
							<span class="step-number">3</span>
						</div>
						<div class="step-label">Create New</div>
						<div class="step-description">Configure Parameters</div>
					</div>
				</div>
			</div>
		`;
	},

	handle_wrench_click: function(frm, row_name) {
		const row = frappe.get_doc(frm.fields_dict.sub_assembly_items.grid.doctype, row_name);
		
		// Fetch Non Standard Item Creation record for this item
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Item Creation',
				filters: {
					new_item_code: row.item_code,
					docstatus: 1
				},
				fields: ['name'],
				limit: 1
			},
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					const ns_item_name = r.message[0].name;
					ujwal_industries.grid_custom_icons.show_non_standard_details_dialog(ns_item_name, frm, row);
				} else {
					frappe.msgprint({
						title: __('Not Found'),
						message: __('No Non-Standard Item Creation record found for: {0}', [row.item_code]),
						indicator: 'red'
					});
				}
			}
		});
		
		const row1 = frappe.get_doc(frm.fields_dict.sub_assembly_items.grid.doctype, row_name);

		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Non Standard Item Creation',
				filters: {
					new_item_code: row1.item_code,
					docstatus: 1
				},
				fields: ['name'],
				limit: 1
			},
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					const ns_item_name = r.message[0].name;
					ujwal_industries.grid_custom_icons.show_non_standard_details_dialog(ns_item_name, frm, row1);
				} else {
					frappe.msgprint({
						title: __('Not Found'),
						message: __('No Non-Standard Item Creation record found for: {0}', [row1.item_code]),
						indicator: 'red'
					});
				}
			}
		});
	},

	show_non_standard_details_dialog: function(ns_item_name, frm, row) {
		// Fetch full Non Standard Item Creation record
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'Non Standard Item Creation',
				name: ns_item_name
			},
			callback: function(r) {
				if (r.message) {
					ujwal_industries.grid_custom_icons.open_ns_details_dialog(r.message, frm, row);
				}
			}
		});
	},

	open_ns_details_dialog: function(ns_record, frm, row) {
		const parameters = ns_record.parameters || [];

		// Build parameters HTML
		let parametersHtml = '';
		if (parameters.length > 0) {
			parametersHtml = '<div style="margin-bottom: 15px;"><div style="font-size: 11px; color: #6c7680; margin-bottom: 8px; font-weight: 600;">PARAMETERS</div><div style="display: grid; gap: 8px;">';
			parameters.forEach(param => {
				const pricingValue = param.pricing_type === 'Percentage'
					? `${param.price_percentage || 0}%`
					: (param.pricing_type === 'Fixed Amount' ? format_currency(param.price_amount || 0, 'INR') : 'Both');

				parametersHtml += `
					<div style="background: white; padding: 10px; border-radius: 6px; border: 1px solid #e8ebed; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; align-items: center;">
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PARAMETER</div>
							<div style="font-size: 12px; font-weight: 700; color: #36414c;">${param.parameter}</div>
						</div>
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">VALUE</div>
							<div style="background: #e8f5e9; color: #2e7d32; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
								${param.selected_value}
							</div>
						</div>
						<div>
							<div style="font-size: 9px; color: #6c7680; margin-bottom: 2px;">PRICE</div>
							<div style="background: #e3f2fd; color: #1976d2; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-align: center;">
								${pricingValue}
							</div>
						</div>
					</div>
				`;
			});
			parametersHtml += '</div></div>';
		}

		const detailDialog = new frappe.ui.Dialog({
			title: __('Non-Standard Item Details - {0}', [ns_record.new_item_code]),
			size: 'large',
			fields: [
				{
					fieldname: 'details_html',
					fieldtype: 'HTML',
					options: `
						<div style="background: #f8f9fa; padding: 15px; border-radius: 6px; margin-bottom: 15px;">
							<div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-bottom: 15px;">
								<div>
									<div style="font-size: 10px; color: #6c7680;">Base Item</div>
									<div style="font-size: 13px; font-weight: 600; color: #36414c;">${ns_record.base_item}</div>
								</div>
								<div>
									<div style="font-size: 10px; color: #6c7680;">Brand</div>
									<div style="font-size: 13px; font-weight: 600; color: #36414c;">${ns_record.brand}</div>
								</div>
								<div>
									<div style="font-size: 10px; color: #6c7680;">Frame Size</div>
									<div style="font-size: 13px; font-weight: 600; color: #36414c;">${ns_record.frame_size || 'N/A'}</div>
								</div>
							</div>
							${parametersHtml}
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 15px; padding-top: 15px; border-top: 0px solid #dee2e6;">
								<div>
									<div style="font-size: 10px; color: #6c7680;">Valuation Price</div>
									<div style="font-size: 16px; font-weight: 600; color: #48bb78;">${format_currency(ns_record.valuation_price || 0, 'INR')}</div>
								</div>
								<div>
									<div style="font-size: 10px; color: #6c7680;">Apply Discount After</div>
									<div style="font-size: 13px; font-weight: 600; color: #36414c;">${ns_record.apply_discount_after || 'Not Set'}</div>
								</div>
							</div>
						</div>
					`
				},
				{
					fieldname: 'section_break',
					fieldtype: 'Section Break',
					label: __('Update Discount')
				},
				{
					fieldname: 'apply_discount_after',
					label: __('Apply Discount After'),
					fieldtype: 'Select',
					options: ns_record.brand === 'Siemens' ? 'Absolute Amount' : '\nPercentage Values',
					default: ns_record.brand === 'Siemens' ? 'Absolute Amount' : (ns_record.apply_discount_after || 'Percentage Values')
				},
				{
					fieldname: 'discount_percentage',
					label: __('Discount Percentage (%)'),
					fieldtype: 'Float',
					default: ns_record.discount_percentage || 0,
					depends_on: 'apply_discount_after'
				}
			],
			primary_action_label: __('Update Discount'),
			primary_action: function(values) {
				ujwal_industries.grid_custom_icons.update_ns_discount_from_grid(ns_record.name, values, detailDialog, frm);
			},
			secondary_action_label: __('View Full Record'),
			secondary_action: function() {
				frappe.set_route('Form', 'Non Standard Item Creation', ns_record.name);
			}
		});

		detailDialog.show();
	},

	update_ns_discount_from_grid: function(ns_item_name, values, detailDialog, frm) {
		// Call server method to update discount
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.doctype.non_standard_item_creation.non_standard_item_creation.update_discount',
			args: {
				docname: ns_item_name,
				apply_discount_after: values.apply_discount_after || null,
				discount_percentage: values.discount_percentage || 0,
				reference_doctype: frm.doctype,
				reference_name: frm.doc.name
			},
			callback: function(r) {
				if (r.message) {
					frappe.show_alert({
						message: __('Discount updated successfully. New price: {0}', [format_currency(r.message.new_price, 'INR')]),
						indicator: 'green'
					}, 5);
					detailDialog.hide();
				}
			},
			error: function(err) {
				frappe.msgprint(__('Error updating discount: {0}', [err.message || err]));
			}
		});
	}
};

// Auto-initialize for applicable doctypes - reliable triggers after grid is loaded
frappe.ui.form.on('Production Plan', {
	refresh: function(frm) {
		ujwal_industries.grid_custom_icons.setup(frm);
	},
	onload_post_render: function(frm) {
		ujwal_industries.grid_custom_icons.setup(frm);
	}
});
frappe.ui.form.on('Purchase Order', {
	refresh: function(frm) {
		ujwal_industries.grid_custom_icons.setup(frm);
	},
	onload_post_render: function(frm) {
		ujwal_industries.grid_custom_icons.setup(frm);
	}
});

frappe.ui.form.on('Sales Order', {
	refresh: function(frm) {
		ujwal_industries.grid_custom_icons.setup(frm);
	},
	onload_post_render: function(frm) {
		ujwal_industries.grid_custom_icons.setup(frm);
	}
});