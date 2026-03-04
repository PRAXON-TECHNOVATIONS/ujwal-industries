
frappe.ui.form.on('Gate Pass', {
    refresh(frm) {
        if(frm.doc.docstatus == 1 && frm.doc.po_number){
            cur_frm.add_custom_button(__('Purchase Receipt'), function(frm) {
                frappe.call({
                    method: "ujwal_industries.ujwal_industries.doctype.gate_pass.gate_pass.custom_make_purchase_receipt",
                    args: {
                        source_name : cur_frm.doc.po_number,
                        gate_pass : cur_frm.doc.name,
                    },
                    freeze_message: __("Creating Purchase Receipt ..."),
                    callback: function(r) {
                        if (r.message) {
                            frappe.set_route("Form", "Purchase Receipt", r.message);
                        }
                    }
                });
            })
        }
	},
    
    delivery_note: function(frm) {

        if (frm.doc.delivery_note) {

            frm.clear_table('gate_pass_detail');
            frm.refresh_field('gate_pass_detail');

            frappe.call({
                method: "ujwal_industries.ujwal_industries.doctype.gate_pass.gate_pass.get_delivery_note_items",
                args: {
                    delivery_note: frm.doc.delivery_note
                },
                callback: function(r) {
                    if (r.message) {
                        r.message.forEach(function(d) {

                            let row = frm.add_child('gate_pass_detail');
                            row.item = d.item;
                            row.qty = d.qty;
                            row.uom = d.uom;
                            row.description = d.description;

                        });

                        frm.refresh_field('gate_pass_detail');
                    }
                }
            });
        }
    },

    po_number: function(frm) {

        if (frm.doc.po_number) {

            frm.clear_table('gate_pass_detail');
            frm.refresh_field('gate_pass_detail');

            frappe.call({
                method: "ujwal_industries.ujwal_industries.doctype.gate_pass.gate_pass.get_po_items",
                args: {
                    po_number: frm.doc.po_number
                },
                callback: function(r) {
                    if (r.message) {
                        r.message.forEach(function(d) {

                            let row = frm.add_child('gate_pass_detail');
                            row.item = d.item;
                            row.qty = d.qty;
                            row.uom = d.uom;
                            row.description = d.description;

                        });

                        frm.refresh_field('gate_pass_detail');
                    }
                }
            });
        }
    }
});
