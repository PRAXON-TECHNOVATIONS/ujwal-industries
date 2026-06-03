import frappe
from erpnext.manufacturing.doctype.job_card.job_card import JobCard
from frappe.utils import flt

def set_process_loss_disabled(self):
    self.process_loss_qty = 0.0

JobCard.set_process_loss = set_process_loss_disabled

def validate_job_card_no_process_loss(self):
    if self.work_order and frappe.get_cached_value(
        "Work Order", self.work_order, "status"
    ) == "Stopped":
        frappe.throw(
            ("Transaction not allowed against stopped Work Order")
        )

    if not self.time_logs:
        frappe.throw(
            ("Time logs are required for Job Card")
        )
    return

JobCard.validate_job_card = validate_job_card_no_process_loss

def update_work_order_no_process_loss(self):
    if not self.work_order or not self.operation_id:
        return

    wo = frappe.get_doc("Work Order", self.work_order)

    for row in wo.operations:
        if row.name == self.operation_id:
            row.completed_qty = flt(self.total_completed_qty)
            row.process_loss_qty = 0  # HARD ZERO

    wo.flags.ignore_validate_update_after_submit = True
    wo.flags.ignore_permissions = True
    wo.save()

JobCard.update_work_order = update_work_order_no_process_loss


from erpnext.manufacturing.doctype.job_card.job_card import JobCard

def on_submit_no_process_loss(self):
    self.db_set("process_loss_qty", 0)

    if hasattr(JobCard, "_original_on_submit"):
        JobCard._original_on_submit(self)

if not hasattr(JobCard, "_original_on_submit"):
    JobCard._original_on_submit = JobCard.on_submit

JobCard.on_submit = on_submit_no_process_loss
