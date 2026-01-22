frappe.ui.form.on("Work Order", {
    refresh: function(frm) {
        // Intercept system Finish button
        frm.page.wrapper.on("click", ".btn[data-label='Finish']", function() {

            let remaining_qty = flt(frm.doc.qty - frm.doc.produced_qty);
            if (remaining_qty <= 0) {
                frappe.msgprint(__("All quantity already produced."));
                return;
            }

            // Fetch custom_tolerance_ from Item
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Item",
                    filters: { name: frm.doc.production_item },
                    fieldname: "custom_tolerance_"
                },
                callback: function(r) {
                    let tolerance_pct = flt(r.message.custom_tolerance_ || 0);
                    let tolerance_qty = remaining_qty * (tolerance_pct / 100);

                    let min_qty = Math.max(0, remaining_qty - tolerance_qty);
                    let max_qty = remaining_qty + tolerance_qty;

                    // Open Finish popup
                    frappe.prompt([
                        {
                            fieldname: "qty",
                            fieldtype: "Float",
                            label: "Quantity to Finish",
                            reqd: 1,
                            default: remaining_qty
                        }
                    ],
                    function(data) {  // Create button click
                        let input_qty = flt(data.qty);

                        // Validate ± tolerance
                        if (input_qty < min_qty || input_qty > max_qty) {
                            frappe.msgprint(__(
                                "Finish quantity must be between {0} and {1} based on tolerance ({2}%)",
                                [min_qty, max_qty, tolerance_pct]
                            ));
                            return;  // reject popup
                        }

                        // Save to custom field for server-side safety
                        frm.set_value("custom_finish_qty", input_qty);

                        // Trigger system Finish logic
                        frm.events.make_stock_entry(frm, input_qty);
                    },
                    __("Select Quantity"),
                    __("Create"));
                }
            });
        });
    }
});
