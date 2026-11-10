// Skills table: rows marked from_job_opening come from the selected Job Opening's
// Required Skills. Changing the Job Opening swaps those rows but keeps any extra
// skills the applicant added, and keeps skill ratings for skills still required.
frappe.ui.form.on("Job Applicant", {
	setup(frm) {
		// Skill Rating mandatory on the desk form only (shows * and blocks save).
		// Not reqd in the doctype JSON, so website applications (which don't show
		// this table) still go through; server validate_skill_ratings is the real check.
		frm.fields_dict.custom_skills.grid.update_docfield_property("rating", "reqd", 1);
	},
	job_title(frm) {
		load_job_opening_skills(frm);
	},
});

function load_job_opening_skills(frm) {
	const rows = frm.doc.custom_skills || [];
	const old_ratings = {};
	rows.forEach((r) => r.skill && (old_ratings[r.skill] = r.rating));

	if (!frm.doc.job_title) {
		frm.set_value(
			"custom_skills",
			rows.filter((r) => !r.from_job_opening)
		);
		return;
	}

	frappe
		.call({
			method: "ujwal_industries.ujwal_industries.overrides.job_applicant.get_job_opening_skills",
			args: { job_opening: frm.doc.job_title },
		})
		.then(({ message: opening_skills = [] }) => {
			const required = new Set(opening_skills.map((s) => s.skill));
			// extra skills the applicant added themselves (not in the new opening)
			const extras = rows.filter((r) => !r.from_job_opening && !required.has(r.skill));

			frm.clear_table("custom_skills");
			opening_skills.forEach((s) => {
				frm.add_child("custom_skills", {
					skill: s.skill,
					description: s.description,
					rating: old_ratings[s.skill] || 0,
					from_job_opening: 1,
				});
			});
			extras.forEach((r) => {
				frm.add_child("custom_skills", {
					skill: r.skill,
					description: r.description,
					rating: r.rating,
					from_job_opening: 0,
				});
			});
			frm.refresh_field("custom_skills");
		});
}
