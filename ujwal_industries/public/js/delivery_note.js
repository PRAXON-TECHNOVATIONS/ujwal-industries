const POSITION_FIELDNAME = "custom_po_no";
const ITEMS_FIELDNAME = "items";
const CHILD_DOCTYPE = "Delivery Note Item";

function set_position_numbers(frm) {
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

frappe.ui.form.on("Delivery Note", {
	setup(frm) {
		set_position_numbers(frm);
	},

	refresh(frm) {
		set_position_numbers(frm);
	},

	validate(frm) {
		set_position_numbers(frm);
	},

	items_add(frm) {
		set_position_numbers(frm);
	},

	items_remove(frm) {
		set_position_numbers(frm);
	},
});

frappe.ui.form.on(CHILD_DOCTYPE, {
	items_add(frm) {
		set_position_numbers(frm);
	},

	items_move(frm) {
		set_position_numbers(frm);
	},

	items_remove(frm) {
		set_position_numbers(frm);
	},
});
