import frappe
from frappe.utils import add_days, flt, nowdate


@frappe.whitelist()
def get_purchase_requisition_display_data():
	"""One row per Material Request Item for open 'Purchase' Material Requests.

	Excludes Cancelled / Stopped / Received / Ordered (fully actioned) MRs, so the list
	shows requisitions that still need a purchasing action. Only items whose planned
	received date (schedule_date) is within ..today+3 are shown (due soon / overdue);
	requisitions planned further out are hidden. Supplier is taken from the Purchase
	Order raised against the MR line (blank until one exists).
	"""
	window_end = add_days(nowdate(), 3)

	rows = frappe.db.sql(
		"""
		SELECT
			mr.name				AS purchase_requisition,
			mr.transaction_date	AS planned_start_date,
			mri.name			AS mr_item_row,
			mri.item_code		AS pr_item_no,
			mri.item_name		AS pr_item_name,
			mri.qty				AS qty,
			mri.schedule_date	AS planned_received_date,
			po.supplier			AS supplier_no,
			po.supplier_name	AS supplier_name
		FROM `tabMaterial Request` mr
		INNER JOIN `tabMaterial Request Item` mri ON mri.parent = mr.name
		LEFT JOIN `tabPurchase Order Item` poi
			ON poi.material_request_item = mri.name AND poi.docstatus < 2
		LEFT JOIN `tabPurchase Order` po
			ON po.name = poi.parent AND po.docstatus < 2
		WHERE
			mr.docstatus < 2
			AND mr.material_request_type = 'Purchase'
			AND mr.status NOT IN ('Cancelled', 'Stopped', 'Received', 'Ordered')
			AND DATE(mri.schedule_date) <= %(window_end)s
		GROUP BY mri.name
		ORDER BY mri.schedule_date ASC, mr.name ASC
		""",
		{"window_end": window_end},
		as_dict=True,
	)

	data = []
	for r in rows:
		data.append(
			{
				"purchase_requisition": r.purchase_requisition,
				"pr_item_no": r.pr_item_no,
				"pr_item_name": r.pr_item_name,
				"planned_start_date": r.planned_start_date,
				"qty": flt(r.qty),
				"planned_received_date": r.planned_received_date,
				"supplier_no": r.supplier_no,
				"supplier_name": r.supplier_name,
			}
		)

	return data
