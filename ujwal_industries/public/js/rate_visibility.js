// Centralised rate/amount field visibility based on user roles.
//
// Who can see rates everywhere:   System Manager, Administrator, Sales & Purchase Head
// Outsource Store Manager:        hidden everywhere EXCEPT Stock Entry
// Everyone else:                  hidden everywhere
(function () {
	function _is_privileged() {
		return (
			frappe.session.user === 'Administrator' ||
			frappe.user_roles.includes('Administrator') ||
			frappe.user_roles.includes('System Manager') ||
			frappe.user_roles.includes('Sales & Purchase Head')
		);
	}

	function _is_outsource_store_mgr() {
		return frappe.user_roles.includes('Outsource Store Manager');
	}

	// ── Field lists ──────────────────────────────────────────────────────────

	// Header-level fields on purchase / sales documents
	var BUYSELL_HEADER = [
		'total', 'net_total', 'base_total', 'base_net_total',
		'grand_total', 'base_grand_total',
		'rounded_total', 'base_rounded_total', 'rounding_adjustment',
		'in_words', 'base_in_words',
		'taxes_and_charges', 'taxes',
		'taxes_and_charges_added', 'taxes_and_charges_deducted',
		'total_taxes_and_charges', 'base_total_taxes_and_charges',
		'other_charges_calculation', 'gst_breakup_table',
		'additional_discount_percentage', 'discount_amount',
		'base_discount_amount',
	];

	// Items child-table fields on purchase / sales documents
	var BUYSELL_ITEMS = [
		'rate', 'amount',
		'price_list_rate', 'base_price_list_rate',
		'base_rate', 'base_amount',
		'net_rate', 'net_amount',
		'base_net_rate', 'base_net_amount',
		'taxable_value',
		'discount_percentage', 'discount_amount',
	];

	// Header-level fields on Stock Entry
	var SE_HEADER = [
		'total_outgoing_value', 'total_incoming_value',
		'value_difference', 'total_additional_costs',
	];

	// Items child-table fields on Stock Entry
	var SE_ITEMS = [
		'basic_rate', 'basic_amount',
		'valuation_rate', 'amount',
		'additional_cost',
	];

	// ── Core hide helper ─────────────────────────────────────────────────────

	// Inject a one-time <style> that makes the cell text invisible in list view
	// columns for the given fieldnames. Columns remain, values are blanked.
	function _inject_css(fields) {
		var id = 'ujwal-rate-hide-css';
		if (document.getElementById(id)) return;

		var selectors = fields.map(function (f) {
			return '.grid-static-col[data-fieldname="' + f + '"] .static-area';
		}).join(', ');

		var style = document.createElement('style');
		style.id = id;
		style.textContent = selectors + ' { color: transparent !important; }';
		document.head.appendChild(style);
	}

	function _apply(frm, header_fields, item_fields) {
		header_fields.forEach(function (f) {
			if (frm.fields_dict[f]) {
				frm.set_df_property(f, 'hidden', 1);
			}
		});
		if (frm.fields_dict && frm.fields_dict.items) {
			item_fields.forEach(function (f) {
				frm.fields_dict.items.grid.update_docfield_property(f, 'hidden', 1);
			});
			frm.refresh_field('items');
		}
		// Blank values in list-view columns (columns stay, text goes invisible)
		_inject_css(item_fields);
	}

	// ── Public API (so individual doctype files can call if needed) ──────────

	window.ujwal_apply_rate_hiding = function (frm) {
		if (_is_privileged()) return;
		// Both Outsource Store Manager and all other roles get hidden on buy/sell docs
		_apply(frm, BUYSELL_HEADER, BUYSELL_ITEMS);
	};

	window.ujwal_apply_rate_hiding_stock_entry = function (frm) {
		if (_is_privileged()) return;
		if (_is_outsource_store_mgr()) return; // Outsource Store Manager can see in Stock Entry
		_apply(frm, SE_HEADER, SE_ITEMS);
	};

	// ── Register handlers for buy / sell doctypes ────────────────────────────

	var BUY_SELL = [
		'Purchase Order', 'Purchase Receipt', 'Purchase Invoice',
		'Sales Order', 'Delivery Note', 'Sales Invoice',
	];

	BUY_SELL.forEach(function (dt) {
		frappe.ui.form.on(dt, {
			onload: function (frm) { ujwal_apply_rate_hiding(frm); },
			refresh: function (frm) { ujwal_apply_rate_hiding(frm); },
		});
	});

	frappe.ui.form.on('Stock Entry', {
		onload: function (frm) { ujwal_apply_rate_hiding_stock_entry(frm); },
		refresh: function (frm) { ujwal_apply_rate_hiding_stock_entry(frm); },
	});
})();
