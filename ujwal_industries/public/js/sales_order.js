const POSITION_FIELDNAME = "custom_po_no";
const ITEMS_FIELDNAME = "items";
const CHILD_DOCTYPE = "Sales Order Item";

// Auto-numbering disabled: Pos. NO. (custom_po_no) is now manually editable
// on Sales Order so users can insert/renumber rows (e.g. 10, 20, 40).
// To revert to auto sequential numbering (10, 20, 30, ...), uncomment the
// set_position_numbers() calls below and restore custom_po_no's read_only
// property to 1 on Sales Order Item.

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

frappe.ui.form.on("Sales Order", {
	setup(frm) {
		// set_position_numbers(frm);
	},

	refresh(frm) {
		// set_position_numbers(frm);
	},

	validate(frm) {
		// set_position_numbers(frm);
	},

	items_add(frm) {
		// set_position_numbers(frm);
	},

	items_remove(frm) {
		// set_position_numbers(frm);
	},
});

frappe.ui.form.on(CHILD_DOCTYPE, {
	items_add(frm) {
		// set_position_numbers(frm);
	},

	items_move(frm) {
		// set_position_numbers(frm);
	},

	items_remove(frm) {
		// set_position_numbers(frm);
	},
});
