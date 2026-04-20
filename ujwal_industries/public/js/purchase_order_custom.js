frappe.ui.form.on('Purchase Order', {
	setup: function () {
		ujwal_patch_po_update_child_items();
	},
	refresh: function (frm) {
		ujwal_patch_po_timeline_reasons(frm);
	},
});

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
				},
				callback: function () {
					frappe.call({
						method: 'ujwal_industries.api.so_revision_log.log_revision',
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
