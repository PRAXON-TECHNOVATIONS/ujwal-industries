from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

_original_update_operations = WorkOrder.update_operation_status

def update_operation_status_no_process_loss(self):
    _original_update_operations(self)

    for op in self.operations:
        op.process_loss_qty = 0

WorkOrder.update_operation_status = update_operation_status_no_process_loss
