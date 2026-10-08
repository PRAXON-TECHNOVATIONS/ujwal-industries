const OT_COMPONENT = "OT Rate";

frappe.ui.form.on("Salary Slip", {
    custom_total_ot_hours(frm) {
        update_ot_rows(frm);
    },
});

frappe.ui.form.on("Salary Detail", {
    salary_component(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.salary_component === OT_COMPONENT) {
            set_ot_amount(frm, row);
        }
    },
});

function update_ot_rows(frm) {
    (frm.doc.earnings || [])
        .filter(r => r.salary_component === OT_COMPONENT)
        .forEach(r => set_ot_amount(frm, r));
}

async function set_ot_amount(frm, row) {
    if (!frm.doc.employee) {
        frappe.msgprint(__("Please select Employee first"));
        return;
    }

    try {
        const { message } = await frappe.db.get_value(
            "Employee", frm.doc.employee, "custom_ot_rate"
        );
        const ot_rate = flt(message?.custom_ot_rate);
        const ot_hours = flt(frm.doc.custom_total_ot_hours);

        if (!ot_rate) {
            frappe.show_alert({
                message: __("OT Rate is not set for Employee {0}", [frm.doc.employee]),
                indicator: "orange",
            });
        }

        await frappe.model.set_value(row.doctype, row.name, "amount", flt(ot_hours * ot_rate, 2));
        frm.refresh_field("earnings");
    } catch (e) {
        console.error(e);
        frappe.msgprint(__("Could not calculate OT amount. Check browser console for details."));
    }
}