frappe.ui.form.on('Purchase Order', {
	setup: function () {
		ujwal_patch_po_update_child_items();
	},
	refresh: function (frm) {
		ujwal_patch_po_timeline_reasons(frm);
		ujwal_add_po_approval_buttons(frm);
		ujwal_show_po_pending_approval_note(frm);
		ujwal_style_po_pending_rows(frm);
		ujwal_fetch_subcontract_po_rates_for_all_rows(frm);
	},
});

frappe.ui.form.on('Purchase Order Item', {
	fg_item(frm, cdt, cdn) {
		// Re-picking the finished good is a deliberate reset — fetch fresh
		// even if this row's rate was locked from a manual edit before.
		frappe.model.set_value(cdt, cdn, 'custom_subcontract_rate_locked', 0);
		ujwal_fetch_subcontract_po_rate(frm, cdt, cdn);
	},

	rate(frm, cdt, cdn) {
		// Only lock on rate edits the USER made — our own fetch sets a guard
		// flag around its own writes so it doesn't lock itself out. Persisted
		// so it survives save/reload, otherwise reopening a draft PO would
		// re-fetch and clobber a rate someone deliberately typed in.
		let row = locals[cdt][cdn];
		if (row.__subcontract_setting_rate) return;
		frappe.model.set_value(cdt, cdn, 'custom_subcontract_rate_locked', 1);
	},
});

function ujwal_fetch_subcontract_po_rate(frm, cdt, cdn) {
	// Subcontracting POs only — the "Job Work" service row's rate should be
	// the finished item's own single-operation Rate/Pc from its default
	// Subcontract row (Item master → Subcontracting Suppliers), the same rate
	// Cost Estimation itself pulls in. This is deliberately NOT the
	// cumulative annexure logic used on the Send to Subcontractor Stock
	// Entry — a subcontracting PO only pays for the one operation it orders.
	//
	// Once a user has typed their own rate on this row
	// (custom_subcontract_rate_locked), this never runs again for it.
	let row = locals[cdt][cdn];
	if (!frm.doc.is_subcontracted || !row.fg_item) return;
	if (row.custom_subcontract_rate_locked) return;

	frappe.call({
		method: 'ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_subcontract_po_rate',
		args: {
			fg_item: row.fg_item,
			company: frm.doc.company,
		},
		callback(r) {
			if (!r.message) return;
			let current = locals[cdt] && locals[cdt][cdn];
			if (!current || current.custom_subcontract_rate_locked) return;

			current.__subcontract_setting_rate = true;
			frappe.model.set_value(cdt, cdn, 'rate', r.message.rate).then(() => {
				current.__subcontract_setting_rate = false;
			});
		},
	});
}

function ujwal_fetch_subcontract_po_rates_for_all_rows(frm) {
	// fg_item rows brought in via "Get Items From" (Production Plan, Material
	// Request, etc.) arrive through a server-side mapper, which doesn't fire
	// the per-row fg_item trigger above — so on load/refresh, sweep every row
	// once and fetch its rate directly. ujwal_fetch_subcontract_po_rate itself
	// skips any row already locked by a manual edit.
	if (!frm.doc.__islocal && frm.doc.docstatus !== 0) return;
	if (!frm.doc.is_subcontracted || !frm.doc.items || !frm.doc.items.length) return;

	frm.doc.items.forEach((row) => {
		if (row.fg_item && !row.__subcontract_rate_fetched) {
			row.__subcontract_rate_fetched = true;
			ujwal_fetch_subcontract_po_rate(frm, row.doctype, row.name);
		}
	});
}

function ujwal_patch_po_update_child_items() {
	if (erpnext.utils.__ujwal_po_patched) return;
	erpnext.utils.__ujwal_po_patched = true;

	const _orig = erpnext.utils.update_child_items;
	erpnext.utils.update_child_items = function (opts) {
		if (opts.frm.doc.doctype !== 'Purchase Order') {
			return _orig.call(this, opts);
		}
		ujwal_po_update_items_dialog(opts);
	};
}

function ujwal_po_update_items_dialog(opts) {
	const frm = opts.frm;
	const cannot_add_row = typeof opts.cannot_add_row === 'undefined' ? true : opts.cannot_add_row;
	const child_docname = typeof opts.cannot_add_row === 'undefined' ? 'items' : opts.child_docname;
	const child_meta = frappe.get_meta('Purchase Order Item');
	const get_precision = (fieldname) => child_meta.fields.find((f) => f.fieldname === fieldname)?.precision || 2;

	const data = (frm.doc[child_docname] || []).map((d) => ({
		docname: d.name,
		name: d.name,
		item_code: d.item_code,
		schedule_date: d.schedule_date,
		conversion_factor: d.conversion_factor,
		qty: d.qty,
		rate: d.rate,
		uom: d.uom,
		fg_item: d.fg_item,
		fg_item_qty: d.fg_item_qty,
	}));

	const fields = [
		{
			fieldtype: 'Data',
			fieldname: 'docname',
			read_only: 1,
			hidden: 1,
		},
		{
			fieldtype: 'Link',
			fieldname: 'item_code',
			options: 'Item',
			in_list_view: 1,
			read_only: 0,
			disabled: 0,
			label: __('Item Code'),
			get_query: function () {
				let filters;
				if (frm.doc.is_subcontracted) {
					if (frm.doc.is_old_subcontracting_flow) {
						filters = { is_sub_contracted_item: 1 };
					} else {
						filters = { is_stock_item: 0 };
					}
				} else {
					filters = { is_purchase_item: 1 };
				}
				return {
					query: 'erpnext.controllers.queries.item_query',
					filters: filters,
				};
			},
			onchange: function () {
				const me = this;

				frm.call({
					method: 'erpnext.stock.get_item_details.get_item_details',
					args: {
						doc: frm.doc,
						args: {
							item_code: this.value,
							set_warehouse: frm.doc.set_warehouse,
							customer: frm.doc.customer || frm.doc.party_name,
							quotation_to: frm.doc.quotation_to,
							supplier: frm.doc.supplier,
							currency: frm.doc.currency,
							is_internal_supplier: frm.doc.is_internal_supplier,
							is_internal_customer: frm.doc.is_internal_customer,
							conversion_rate: frm.doc.conversion_rate,
							price_list: frm.doc.selling_price_list || frm.doc.buying_price_list,
							price_list_currency: frm.doc.price_list_currency,
							plc_conversion_rate: frm.doc.plc_conversion_rate,
							company: frm.doc.company,
							order_type: frm.doc.order_type,
							is_pos: cint(frm.doc.is_pos),
							is_return: cint(frm.doc.is_return),
							is_subcontracted: frm.doc.is_subcontracted,
							ignore_pricing_rule: frm.doc.ignore_pricing_rule,
							doctype: frm.doc.doctype,
							name: frm.doc.name,
							qty: me.doc.qty || 1,
							uom: me.doc.uom,
							pos_profile: cint(frm.doc.is_pos) ? frm.doc.pos_profile : '',
							tax_category: frm.doc.tax_category,
							child_doctype: frm.doc.doctype + ' Item',
							is_old_subcontracting_flow: frm.doc.is_old_subcontracting_flow,
						},
					},
					callback: function (r) {
						if (r.message) {
							const { qty, price_list_rate: rate, uom, conversion_factor, bom_no } = r.message;

							const row = dialog.fields_dict.trans_items.df.data.find((doc) => doc.idx == me.doc.idx);
							if (row) {
								Object.assign(row, {
									conversion_factor: me.doc.conversion_factor || conversion_factor,
									uom: me.doc.uom || uom,
									qty: me.doc.qty || qty,
									rate: me.doc.rate || rate,
									bom_no: bom_no,
								});
								dialog.fields_dict.trans_items.grid.refresh();
							}
						}
					},
				});
			},
		},
		{
			fieldtype: 'Date',
			fieldname: 'schedule_date',
			in_list_view: 1,
			label: __('Reqd by date'),
			reqd: 1,
		},
		{
			fieldtype: 'Float',
			fieldname: 'conversion_factor',
			label: __('Conversion Factor'),
			precision: get_precision('conversion_factor'),
		},
		{
			fieldtype: 'Link',
			fieldname: 'uom',
			options: 'UOM',
			read_only: 0,
			label: __('UOM'),
			reqd: 1,
			onchange: function () {
				frappe.call({
					method: 'erpnext.stock.get_item_details.get_conversion_factor',
					args: { item_code: this.doc.item_code, uom: this.value },
					callback: (r) => {
						if (!r.exc) {
							if (this.doc.conversion_factor == r.message.conversion_factor) return;

							const docname = this.doc.docname;
							dialog.fields_dict.trans_items.df.data.some((doc) => {
								if (doc.docname == docname) {
									doc.conversion_factor = r.message.conversion_factor;
									dialog.fields_dict.trans_items.grid.refresh();
									return true;
								}
							});
						}
					},
				});
			},
		},
		{
			fieldtype: 'Float',
			fieldname: 'qty',
			default: 0,
			read_only: 0,
			in_list_view: 1,
			label: __('Qty'),
			precision: get_precision('qty'),
		},
		{
			fieldtype: 'Currency',
			fieldname: 'rate',
			options: 'currency',
			default: 0,
			read_only: 0,
			in_list_view: 1,
			label: __('Rate'),
			precision: get_precision('rate'),
		},
	];

	if (frm.doc.is_subcontracted && !frm.doc.is_old_subcontracting_flow) {
		fields.push(
			{
				fieldtype: 'Link',
				fieldname: 'fg_item',
				options: 'Item',
				reqd: 1,
				in_list_view: 0,
				read_only: 0,
				disabled: 0,
				label: __('Finished Good Item'),
				get_query: () => ({
					filters: {
						is_stock_item: 1,
						is_sub_contracted_item: 1,
						default_bom: ['!=', ''],
					},
				}),
				onchange: function () {
					const me = this;
					if (!me.value) return;

					frappe.call({
						method: 'ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_subcontract_po_rate',
						args: {
							fg_item: me.value,
							company: frm.doc.company,
						},
						callback: function (r) {
							if (!r.message) return;

							const row = dialog.fields_dict.trans_items.df.data.find((doc) => doc.idx == me.doc.idx);
							if (row) {
								row.rate = r.message.rate;
								dialog.fields_dict.trans_items.grid.refresh();
							}
						},
					});
				},
			},
			{
				fieldtype: 'Float',
				fieldname: 'fg_item_qty',
				reqd: 1,
				default: 0,
				read_only: 0,
				in_list_view: 0,
				label: __('Finished Good Item Qty'),
				precision: get_precision('fg_item_qty'),
			}
		);
	}

	let dialog = new frappe.ui.Dialog({
		title: __('Update Items'),
		size: 'extra-large',
		fields: [
			{
				fieldname: 'trans_items',
				fieldtype: 'Table',
				label: 'Items',
				cannot_add_rows: cannot_add_row,
				in_place_edit: false,
				reqd: 1,
				data: data,
				get_data: () => data,
				fields: fields,
			},
			{ fieldtype: 'Section Break' },
			{
				fieldname: 'reason',
				fieldtype: 'Small Text',
				label: __('Reason'),
				reqd: 1,
				description: __('Mandatory: Provide a reason for this update'),
			},
		],
		primary_action_label: __('Update'),
		primary_action: function () {
			const values = dialog.get_values();
			if (!values) return;

			const trans_items = (values.trans_items || []).filter((item) => !!item.item_code);

			frappe.call({
				method: 'erpnext.controllers.accounts_controller.update_child_qty_rate',
				freeze: true,
				args: {
					parent_doctype: frm.doc.doctype,
					trans_items: trans_items,
					parent_doctype_name: frm.doc.name,
					child_docname: child_docname,
					reason: values.reason,
				},
				callback: function () {
					frm.reload_doc();
				},
			});

			dialog.hide();
			refresh_field('items');
		},
	});

	dialog.show();
}

function ujwal_patch_po_timeline_reasons(frm) {
	if (!frm.timeline || frm.timeline.__ujwal_reasons_patched) return;
	frm.timeline.__ujwal_reasons_patched = true;

	const _orig = frm.timeline.get_version_timeline_contents.bind(frm.timeline);

	frm.timeline.get_version_timeline_contents = function () {
		const contents = _orig();
		const versions = (this.doc_info && this.doc_info.versions) || [];

		return contents.map((item) => {
			const version = versions.find((v) => v.creation === item.creation);
			if (version) {
				try {
					const vdata = JSON.parse(version.data || '{}');
					if (vdata.reason) {
						return {
							...item,
							content:
								item.content +
								`<br><span style="font-size:13px">Reason: <b>${frappe.utils.escape_html(vdata.reason)}</b></span>`,
						};
					}
				} catch (_) {}
			}
			return item;
		});
	};
}

function ujwal_add_po_approval_buttons(frm) {
	if (frm.doc.docstatus !== 1 || !ujwal_po_has_pending_rows(frm) || !ujwal_can_approve_po_updates()) {
		return;
	}

	frm.add_custom_button(__('Approve'), function () {
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.sales_order_update_items.approve_pending_item_updates',
			freeze: true,
			args: {
				doctype: frm.doc.doctype,
				docname: frm.doc.name,
			},
			callback: function () {
				frm.reload_doc();
			},
		});
	});

	frm.add_custom_button(__('Reject'), function () {
		frappe.prompt(
			[
				{
					fieldname: 'reason',
					fieldtype: 'Small Text',
					label: __('Rejection Reason'),
					reqd: 0,
				},
			],
			(values) => {
				frappe.call({
					method: 'ujwal_industries.ujwal_industries.overrides.sales_order_update_items.reject_pending_item_updates',
					freeze: true,
					args: {
						doctype: frm.doc.doctype,
						docname: frm.doc.name,
						reason: values.reason,
					},
					callback: function () {
						frm.reload_doc();
					},
				});
			},
			__('Reject Pending Item Updates'),
			__('Reject')
		);
	});

	frm.change_custom_button_type(__('Approve'), null, 'primary');
	frm.change_custom_button_type(__('Reject'), null, 'danger');
}

function ujwal_show_po_pending_approval_note(frm) {
	const wrapper = frm.dashboard && frm.dashboard.wrapper ? $(frm.dashboard.wrapper) : null;
	if (!wrapper || !wrapper.length) {
		return;
	}

	wrapper.find('.ujwal-po-pending-approval-note').remove();

	const pendingRows = (frm.doc.items || []).filter(
		(row) => row.custom_update_approval_status === 'Pending Approval'
	);

	if (!pendingRows.length) {
		return;
	}

	const rowHtml = pendingRows
		.map((row) => {
			const requestData = ujwal_parse_po_request_data(row.custom_update_request_data);
			const requester = requestData.requested_by || __('Unknown User');
			const reason = requestData.reason || row.custom_update_request_reason || __('No reason provided');
			const changedFields = (requestData.changed_fields || []).join(', ') || __('details updated');
			return `
				<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(107, 114, 128, 0.18);">
					<div><strong>Row ${frappe.utils.escape_html(String(row.idx || ''))}</strong> - ${frappe.utils.escape_html(row.item_code || '')}</div>
					<div style="margin-top:4px;color:#374151;">Requested by: ${frappe.utils.escape_html(requester)}</div>
					<div style="margin-top:2px;color:#4b5563;">Changed: ${frappe.utils.escape_html(changedFields)}</div>
					<div style="margin-top:2px;color:#111827;"><strong>Reason:</strong> ${frappe.utils.escape_html(reason)}</div>
				</div>
			`;
		})
		.join('');

	const noteHtml = `
		<div class="ujwal-po-pending-approval-note" style="margin:12px 0 8px;padding:14px 16px;border-radius:12px;border:1px solid #d1d5db;background:linear-gradient(180deg,#f9fafb 0%,#f3f4f6 100%);box-shadow:0 8px 24px rgba(17,24,39,0.05);">
			<div style="font-size:13px;font-weight:700;letter-spacing:0.02em;color:#374151;">Pending Item Update Approval</div>
			<div style="margin-top:4px;color:#4b5563;">Review the requester reason below before approving or rejecting these changes.</div>
			${rowHtml}
		</div>
	`;

	wrapper.prepend(noteHtml);
}

function ujwal_parse_po_request_data(requestData) {
	if (!requestData) {
		return {};
	}

	try {
		return typeof requestData === 'string' ? JSON.parse(requestData) : requestData;
	} catch (error) {
		return {};
	}
}

function ujwal_po_has_pending_rows(frm) {
	return (frm.doc.items || []).some((row) => row.custom_update_approval_status === 'Pending Approval');
}

function ujwal_can_approve_po_updates() {
	return frappe.session.user === 'Administrator'
		|| frappe.user.has_role('Purchase Manager')
		|| frappe.user.has_role('System Manager');
}

function ujwal_style_po_pending_rows(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;

	setTimeout(() => {
		(grid.grid_rows || []).forEach((grid_row) => {
			const is_pending = grid_row.doc && grid_row.doc.custom_update_approval_status === 'Pending Approval';
			const background = is_pending ? '#e0e0e0' : '';

			$(grid_row.row).css('background-color', background);
			$(grid_row.row).find('.data-row, .grid-static-col').css('background-color', background);

			if (grid_row.grid_form) {
				$(grid_row.grid_form.wrapper).css('background-color', background);
			}
		});
	}, 0);
}
