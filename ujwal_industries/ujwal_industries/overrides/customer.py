import frappe
from frappe import _
from frappe.model.document import Document

def autoname(self, method):

    if not self.customer_group:
        return
    
    buying_setting = frappe.get_single("Buying Settings")
    if buying_setting.applicable_customer_naming_series == 1:
        matched_row = None
        if buying_setting.customer_naming_series:
            for row in buying_setting.customer_naming_series:
                if row.customer_group == self.customer_group:
                    matched_row = row
                    break
        
        if not matched_row:
            frappe.throw(f"No Naming Series Defined for Customer Group in Buying Settings <b>{self.customer_group}</b>")
        
        
        from_start = int(matched_row.from_start)
        to_end = int(matched_row.to_end) 
        
        frappe.db.sql(
                """
                SELECT current_no
                FROM `tabCustomer Naming Series`
                WHERE name = %s
                FOR UPDATE
                """,matched_row.name)

        current_no = frappe.db.get_value("Customer Naming Series", matched_row.name, "current_no")

        if current_no:
            try:
                current_no_int = int(''.join(filter(str.isdigit, current_no)))
            except:
                current_no_int = 0
        else:
            current_no_int = from_start

        next_no = current_no_int + 1

        if next_no > to_end:
            frappe.throw(
                f"Naming series out of range for Customer Group {self.customer_group}. "
                f"Allowed Range: {from_start} to {to_end}"
            )

        self.name = str(next_no)
        frappe.db.set_value("Customer Naming Series", matched_row.name,"current_no",next_no)
    
    else:
        frappe.msgprint("Dynamic Customer Naming Series is Currently Disabled in Buying Settings. Please Enable it to Apply Automatic Numbering.")
        
    self.custom_customer_names = self.customer_name