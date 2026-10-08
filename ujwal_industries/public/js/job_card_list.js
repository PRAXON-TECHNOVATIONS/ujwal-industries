// Job Card list view — display label override for submitted job cards.
//
// "Completed" status is reused as a pre-submit signal (see
// apply_order_completed_status in job_card.py) so reports/displays that
// filter on status="Completed" keep working unchanged. Once the document is
// actually submitted, show "Submitted" in the list view indicator only — the
// underlying status field stays "Completed" in the database.

frappe.listview_settings["Job Card"] = frappe.listview_settings["Job Card"] || {};

const _orig_get_indicator_jc = frappe.listview_settings["Job Card"].get_indicator;

frappe.listview_settings["Job Card"].get_indicator = function (doc) {
	if (doc.docstatus === 1 && doc.status === "Completed") {
		return [__("Submitted"), "blue", "docstatus,=,1"];
	}
	if (_orig_get_indicator_jc) return _orig_get_indicator_jc(doc);
};
