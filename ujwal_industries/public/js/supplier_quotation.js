frappe.ui.form.on("Supplier Quotation", {
    custom_default_payment_terms_template: function(frm) {
        if (!frm.doc.custom_default_payment_terms_template) {
            frm.clear_table("custom_payment_term_details");
            frm.refresh_field("custom_payment_term_details");
            return;
        }
        frappe.call({
            method: "frappe.client.get",
            args: {
                doctype: "Payment Terms Template",
                name: frm.doc.custom_default_payment_terms_template
            },
            callback: function(r) {
                if (!r.message) return;

                let terms = r.message.terms || [];
                frm.clear_table("custom_payment_term_details");
                terms.forEach(row => {
                    let d = frm.add_child("custom_payment_term_details");
                    d.payment_term = row.payment_term;
                    d.description = row.description;
                    d.due_date_based_on = row.due_date_based_on;
                    d.invoice_portion = row.invoice_portion;
                    d.credit_days = row.credit_days;
                    d.credit_months = row.credit_months;
                    d.due_date = row.due_date;
                });

                frm.refresh_field("custom_payment_term_details");
            }
        });
    }
});
