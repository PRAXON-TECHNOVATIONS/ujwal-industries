import frappe
from frappe import _
from frappe.model.document import Document

def check_duplicate_gstin(doc, method):
    if not doc.gstin:
        return

    gstin = doc.gstin.strip().upper()

    duplicate = frappe.db.sql("""
        SELECT name
        FROM `tabSupplier`
        WHERE gstin IS NOT NULL
          AND gstin != ''
          AND UPPER(gstin) = %s
          AND name != %s
        LIMIT 1
    """, (gstin, doc.name), as_dict=True)

    if duplicate:
        frappe.throw(
            f"""
            Duplicate GSTIN not allowed.<br><br>
            GSTIN <b>{gstin}</b> already exists in Supplier
            <b>{duplicate[0].name}</b>
            """
        )



def autoname(self, method):
    if not self.supplier_group:
        return
    
    buying_setting = frappe.get_single("Buying Settings")
    if buying_setting.applicable_supplier_naming_series == 1:
        matched_row = None
        if buying_setting.supplier_naming_series:
            for row in buying_setting.supplier_naming_series:
                if row.supplier_group == self.supplier_group:
                    matched_row = row
                    break
        
        if not matched_row:
            frappe.throw(f"No Naming Series Defined for Supplier Group in Buying Settings <b>{self.supplier_group}</b>")
        
        
        from_start = int(matched_row.from_start)
        to_end = int(matched_row.to_end) 
        
        frappe.db.sql(
                """
                SELECT current_no
                FROM `tabSupplier Naming Series`
                WHERE name = %s
                FOR UPDATE
                """,matched_row.name)

        current_no = frappe.db.get_value("Supplier Naming Series", matched_row.name, "current_no")

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
                f"Naming series out of range for Supplier Group {self.supplier_group}. "
                f"Allowed Range: {from_start} to {to_end}"
            )

        self.name = str(next_no)
        frappe.db.set_value("Supplier Naming Series", matched_row.name,"current_no",next_no)
    
    else:
        frappe.msgprint("Dynamic Supplier Naming Series is Currently Disabled in Buying Settings. Please Enable it to Apply Automatic Numbering.")