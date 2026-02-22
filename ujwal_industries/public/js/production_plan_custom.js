// Custom script for Production Plan to show Bulk Pre Production Plan reference

frappe.ui.form.on('Production Plan', {
	refresh: function(frm) {
		if (frm.doc.name && !frm.doc.__islocal) {
			// Check if this Production Plan is linked to a Bulk Pre Production Plan
			check_and_render_bulk_pp_reference(frm);
		}
	},
});


function check_and_render_bulk_pp_reference(frm) {
	/**
	 * Check if this Production Plan was created from a Bulk Pre Production Plan
	 * and render a sidebar widget with the link
	 */

	frappe.call({
		method: 'ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.get_bulk_pp_for_production_plan',
		args: {
			production_plan: frm.doc.name
		},
		callback: function(r) {
			if (r.message && r.message.bulk_pp) {
				render_bulk_pp_sidebar(frm, r.message);
			}
		}
	});
}


function render_bulk_pp_sidebar(frm, data) {
	/**
	 * Render Bulk Pre Production Plan reference in sidebar
	 */

	if (!data || !data.bulk_pp) return;

	let html = `
		<div class="bulk-pp-sidebar-info" style="margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 5px; border-left: 3px solid #2490ef;">
			<h6 style="margin-bottom: 8px; color: #333; font-weight: 600;">
				<i class="fa fa-link" style="color: #2490ef;"></i> Bulk Production Plan
			</h6>
			<div style="font-size: 12px; line-height: 1.6;">
				<div style="margin-bottom: 4px;">
					<span style="color: #6c757d;">Plan:</span>
					<strong style="color: #333;">${data.bulk_pp}</strong>
				</div>
				${data.sales_order ? `
					<div style="margin-bottom: 4px;">
						<span style="color: #6c757d;">Sales Order:</span>
						<span class="badge badge-primary" style="font-size: 10px;">${data.sales_order}</span>
					</div>
				` : ''}
				${data.posting_date ? `
					<div style="margin-bottom: 4px;">
						<span style="color: #6c757d;">Date:</span>
						<span style="color: #333;">${frappe.format(data.posting_date, {fieldtype: 'Date'})}</span>
					</div>
				` : ''}
				${data.status ? `
					<div style="margin-bottom: 4px;">
						<span style="color: #6c757d;">Status:</span>
						<span class="badge badge-info" style="font-size: 10px;">${data.status}</span>
					</div>
				` : ''}
				<div style="margin-top: 8px;">
					<a href="/app/bulk-pre-production-plan/${data.bulk_pp}" target="_blank" style="font-size: 11px;">
						View Bulk Plan <i class="fa fa-external-link"></i>
					</a>
				</div>
			</div>
		</div>
	`;

	// Add to sidebar - remove existing first to avoid duplicates
	$(frm.wrapper).find('.form-sidebar .bulk-pp-sidebar-info').remove();
	$(frm.wrapper).find('.form-sidebar .sidebar-menu').first().before(html);
}
