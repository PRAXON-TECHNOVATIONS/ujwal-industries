frappe.ui.form.on("Material Request Item", {
    item_code(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.item_code) return;
        let duplicate = frm.doc.items.filter(i => i.item_code === row.item_code);

        if (duplicate.length > 1) {
            frappe.msgprint({
                title: "Duplicate Item",
                indicator: "red",
                message: `Item <b>${row.item_code}</b> has been entered multiple times`
            });
            frappe.model.set_value(cdt, cdn, "item_code", "");
        }
    }
});

frappe.ui.form.on('Material Request', {
    refresh(frm) {
    //     setTimeout(() => {
    //         ['Bill of Materials', 'Sales Order', 'Product Bundle'].forEach(btn => {
    //             frm.remove_custom_button(btn, 'Get Items From');
    //         });
    //     }, 100);
        if (frm.fields_dict.material_request_type) {
            frm.set_df_property(
                'material_request_type',
                'options',
                ['Purchase', 'Material Transfer' , 'Manufacture'].join('\n')
            );
        }
        if (frm.doc.docstatus === 1) {
            add_custom_po_button(frm);
        }
    }
});
function add_custom_po_button(frm) {
    frm.remove_custom_button(__('Purchase Order'), __('Create'));

    frm.add_custom_button(__('Purchase Order'), () => {
        frappe.call({
            method: 'ujwal_industries.api.create_po_from_mr.make_po_from_mr',
            args: { material_request: frm.doc.name }
        }).then(r => {
            if (!r.message) return;

            let doc = frappe.model.sync(r.message)[0];
            frappe.set_route('Form', doc.doctype, doc.name);
        });
    }, __('Create'));
}
