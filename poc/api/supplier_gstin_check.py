import frappe

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
