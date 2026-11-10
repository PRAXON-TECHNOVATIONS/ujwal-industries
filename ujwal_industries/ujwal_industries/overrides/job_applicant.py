import frappe


def copy_job_opening_skills(doc, method=None):
	"""On a new Job Applicant, copy the Job Opening's Required Skills into the
	applicant's Skills table. Runs server-side so applications from the website
	form (or created via API) get the skills too. Skips if the table already has
	opening rows (the form JS fills them when Job Opening is picked)."""
	if not doc.job_title:
		return
	if any(row.from_job_opening for row in doc.get("custom_skills") or []):
		return

	existing = {row.skill for row in doc.get("custom_skills") or []}
	for s in get_job_opening_skills(doc.job_title):
		if s.skill in existing:
			continue
		doc.append(
			"custom_skills",
			{"skill": s.skill, "description": s.description, "from_job_opening": 1},
		)


@frappe.whitelist()
def get_job_opening_skills(job_opening):
	return frappe.get_all(
		"Job Opening Skill",
		filters={"parent": job_opening, "parenttype": "Job Opening", "parentfield": "custom_required_skills"},
		fields=["skill", "description"],
		order_by="idx asc",
	)


def validate_skill_ratings(doc, method=None):
	"""Skill Rating is mandatory on every Skills row. A 0-star rating counts as
	missing (Frappe's own reqd check treats 0 as filled, so we check here).
	Website applications (Guest) are skipped: the web form doesn't show this
	table, so HR fills the ratings later in the desk form."""
	if frappe.session.user == "Guest":
		return

	missing = [
		f"#{row.idx} {row.skill or ''}".strip()
		for row in doc.get("custom_skills") or []
		if not row.rating
	]
	if missing:
		frappe.throw(
			frappe._("Skill Rating is mandatory in the Skills table. Please rate rows: {0}").format(
				", ".join(missing)
			),
			title=frappe._("Skill Rating Missing"),
		)
