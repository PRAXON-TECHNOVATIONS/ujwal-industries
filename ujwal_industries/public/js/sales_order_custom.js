const POSITION_FIELDNAME = 'custom_po_no';
const ITEMS_FIELDNAME = 'items';
const SALES_ORDER_ITEM_DOCTYPE = 'Sales Order Item';

frappe.ui.form.on('Sales Order', {
	setup: function (frm) {
		ujwal_patch_so_update_child_items();
		ujwal_configure_so_position_number_field(frm);
		ujwal_set_so_position_numbers(frm);
	},
	refresh: function (frm) {
		ujwal_configure_so_position_number_field(frm);
		ujwal_patch_timeline_reasons(frm);
	},
	validate: function (frm) {
		ujwal_set_so_position_numbers(frm);
	},
	items_add: function (frm) {
		ujwal_set_so_position_numbers(frm);
	},
	items_remove: function (frm) {
		ujwal_set_so_position_numbers(frm);
	},
});

frappe.ui.form.on(SALES_ORDER_ITEM_DOCTYPE, {
	items_add: function (frm) {
		ujwal_set_so_position_numbers(frm);
	},
	items_move: function (frm) {
		ujwal_set_so_position_numbers(frm);
	},
	items_remove: function (frm) {
		ujwal_set_so_position_numbers(frm);
	},
});

function ujwal_configure_so_position_number_field(frm) {
	const items_grid = frm.fields_dict[ITEMS_FIELDNAME] && frm.fields_dict[ITEMS_FIELDNAME].grid;
	if (!items_grid) {
		return;
	}

	items_grid.update_docfield_property(POSITION_FIELDNAME, 'hidden', 0);
	items_grid.update_docfield_property(POSITION_FIELDNAME, 'in_list_view', 1);
	items_grid.update_docfield_property(POSITION_FIELDNAME, 'read_only', 1);
	frm.refresh_field(ITEMS_FIELDNAME);
}

function ujwal_set_so_position_numbers(frm) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const items = frm.doc[ITEMS_FIELDNAME] || [];
	let has_changes = false;

	items.forEach((row, index) => {
		const position_number = String((index + 1) * 10);
		if (row[POSITION_FIELDNAME] !== position_number) {
			row[POSITION_FIELDNAME] = position_number;
			has_changes = true;
		}
	});

	if (has_changes) {
		frm.refresh_field(ITEMS_FIELDNAME);
		frm.dirty();
	}
}

// ── Patch "Update Items" dialog to require a Reason ──────────────────────────

function ujwal_patch_so_update_child_items() {
	if (erpnext.utils.__ujwal_so_patched) return;
	erpnext.utils.__ujwal_so_patched = true;

	const _orig = erpnext.utils.update_child_items;
	erpnext.utils.update_child_items = function (opts) {
		if (opts.frm.doc.doctype !== 'Sales Order') {
			return _orig.call(this, opts);
		}
		ujwal_so_update_items_dialog(opts);
	};
}

function ujwal_so_update_items_dialog(opts) {
	const frm = opts.frm;
	const child_docname = opts.child_docname || 'items';
	const child_meta = frappe.get_meta('Sales Order Item');
	const get_precision = (fn) => {
		const f = child_meta && child_meta.fields.find((x) => x.fieldname === fn);
		return f ? f.precision : 2;
	};

	const data = (frm.doc[child_docname] || []).map((d) => ({
		docname: d.name,
		item_code: d.item_code,
		delivery_date: d.delivery_date,
		qty: d.qty,
		rate: d.rate,
		uom: d.uom,
		conversion_factor: d.conversion_factor,
	}));

	const table_fields = [
		{ fieldtype: 'Data', fieldname: 'docname', hidden: 1 },
		{
			fieldtype: 'Link',
			fieldname: 'item_code',
			options: 'Item',
			in_list_view: 1,
			label: __('Item Code'),
			get_query: () => ({ filters: { is_sales_item: 1 } }),
		},
		{ fieldtype: 'Data', fieldname: 'uom', hidden: 1 },
		{ fieldtype: 'Float', fieldname: 'conversion_factor', hidden: 1 },
		{
			fieldtype: 'Date',
			fieldname: 'delivery_date',
			in_list_view: 1,
			label: __('Delivery Date'),
			reqd: 1,
		},
		{
			fieldtype: 'Float',
			fieldname: 'qty',
			default: 0,
			in_list_view: 1,
			label: __('Qty'),
			precision: get_precision('qty'),
		},
		{
			fieldtype: 'Currency',
			fieldname: 'rate',
			options: 'currency',
			default: 0,
			in_list_view: 1,
			label: __('Rate'),
			precision: get_precision('rate'),
		},
	];

	let dialog = new frappe.ui.Dialog({
		title: __('Update Items'),
		size: 'extra-large',
		fields: [
			{
				fieldname: 'trans_items',
				fieldtype: 'Table',
				label: 'Items',
				cannot_add_rows: false,
				in_place_edit: false,
				reqd: 1,
				data: data,
				get_data: () => data,
				fields: table_fields,
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
							sales_order: frm.doc.name,
							reason: values.reason,
						},
						callback: function () {
							frm.reload_doc();
						},
					});
				},
			});

			dialog.hide();
		},
	});

	dialog.show();
}

// ── Patch timeline to show Reason inline with the Version entry ──────────────

function ujwal_patch_timeline_reasons(frm) {
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
