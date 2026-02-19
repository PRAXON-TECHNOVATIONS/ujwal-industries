app_name = "ujwal_industries"
app_title = "Ujwal Industries"
app_publisher = "Ujjwal Aggrawal"
app_description = "Custom application for all sorts of customizations"
app_email = "ujjmee2279@gmail.com"
app_license = "mit"


# Import your override at bench startup
from ujwal_industries.overrides import stock_entry_override
from ujwal_industries.overrides import job_card_override
from ujwal_industries.overrides import work_order_override
# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "ujwal_industries",
# 		"logo": "/assets/ujwal_industries/logo.png",
# 		"title": "Ujwal Industries",
# 		"route": "/ujwal_industries",
# 		"has_permission": "ujwal_industries.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/ujwal_industries/css/ujwal_industries.css"
# app_include_js = "/assets/ujwal_industries/js/ujwal_industries.js"
# include js, css files in header of web template
# web_include_css = "/assets/ujwal_industries/css/ujwal_industries.css"
# web_include_js = "/assets/ujwal_industries/js/ujwal_industries.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "ujwal_industries/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Production Plan": "public/js/production_plan_subcontracting.js",
	"Supplier": "public/js/supplier.js",
	"Supplier Quotation": "public/js/supplier_quotation.js",
	"Material Request": "public/js/material_request.js",
	"Job Card": "public/js/job_card.js",
	"Workstation": "public/js/workstation.js",
 	"Work Order": "public/js/work_order_scrap.js",
  	"Stock Entry": "public/js/stock_entry.js"
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "ujwal_industries/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "ujwal_industries.utils.jinja_methods",
# 	"filters": "ujwal_industries.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "ujwal_industries.install.before_install"
# after_install = "ujwal_industries.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "ujwal_industries.uninstall.before_uninstall"
# after_uninstall = "ujwal_industries.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "ujwal_industries.utils.before_app_install"
# after_app_install = "ujwal_industries.utils.after_app_install"
after_migrate = "ujwal_industries.ujwal_industries.patches.migrate_custom_fields.run_all"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "ujwal_industries.utils.before_app_uninstall"
# after_app_uninstall = "ujwal_industries.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "ujwal_industries.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Workstation": "ujwal_industries.ujwal_industries.overrides.workstation.has_permission_query_workstation",
	"Job Card": "ujwal_industries.ujwal_industries.overrides.workstation.has_permission_query_job_card",
}
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Production Plan": "ujwal_industries.ujwal_industries.overrides.production_plan_class.CustomProductionPlan"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Item": {
		"validate": "ujwal_industries.ujwal_industries.overrides.item.validate_subcontracting_suppliers"
	},
 	"Stock Entry": {
        "validate": [
            "ujwal_industries.ujwal_industries.overrides.stock_entry.validate_scrap_item_tolerance"
        ]
    },
	"Production Plan": {
		"onload": "ujwal_industries.ujwal_industries.overrides.production_plan.onload_production_plan",
		"validate": [
      				"ujwal_industries.ujwal_industries.overrides.production_plan.validate_planned_start_dates",
                      "ujwal_industries.ujwal_industries.overrides.production_plan.update_schedule_date",
               		],
  
  
		"before_save": [
			"ujwal_industries.ujwal_industries.overrides.production_plan.set_planned_start_dates",
			"ujwal_industries.ujwal_industries.overrides.production_plan.set_subcontracting_suppliers",
			"ujwal_industries.ujwal_industries.overrides.production_plan.master_set_fg_dates_by_type",
			"ujwal_industries.ujwal_industries.overrides.production_plan.adjust_mr_items_and_propagate"
		]
	},
	"Supplier": {
		"before_save": "ujwal_industries.api.supplier_gstin_check.check_duplicate_gstin"
	},
	"Material Request": {
		"before_insert": "ujwal_industries.ujwal_industries.patches.mr_reorder.set_reorder_field"
	},
	"Job Card": {
		"onload": "ujwal_industries.ujwal_industries.overrides.job_card.onload_job_card",
		"before_submit": "ujwal_industries.ujwal_industries.overrides.job_card.override_job_card_qty_validation",
        "before_save": "ujwal_industries.ujwal_industries.overrides.job_card.restrict_job_card_edit_during_downtime",
        "validate": [
            "ujwal_industries.ujwal_industries.overrides.job_card.job_card_validate"
        ],
	},
	"Downtime Entry": {
		"after_insert": "ujwal_industries.ujwal_industries.overrides.downtime_entry.on_save_downtime_entry",
		"on_update": "ujwal_industries.ujwal_industries.overrides.downtime_entry.on_save_downtime_entry",
		"on_trash": "ujwal_industries.ujwal_industries.overrides.downtime_entry.on_trash_downtime_entry",
  		"validate": "ujwal_industries.ujwal_industries.overrides.downtime_entry.validate_downtime_entry",
	},
	"Purchase Receipt": {
        "before_submit": "ujwal_industries.ujwal_industries.overrides.purchase_receipt.validate_processing_time_before_submit"
    },
	"Data Import": {
		"validate": "ujwal_industries.ujwal_industries.overrides.data_import.validate_production_plan_import"
	},
	"Work Order":{
		"before_insert": "ujwal_industries.ujwal_industries.overrides.work_order.set_wip_before_insert"
	},
 	"Quality Inspection": {
        "on_submit": "ujwal_industries.ujwal_industries.overrides.quality_inspection.update_grn_processing_time"
    }
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"* * * * *": [
			"ujwal_industries.ujwal_industries.overrides.downtime_entry.sync_workstation_statuses"
		]
	},
}

# Testing
# -------

# before_tests = "ujwal_industries.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "ujwal_industries.event.get_events"
# }
override_whitelisted_methods = {
    "erpnext.manufacturing.doctype.job_card.job_card.make_time_log":
        "ujwal_industries.ujwal_industries.overrides.job_card.make_time_log_with_material_check"
}

#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "ujwal_industries.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["ujwal_industries.utils.before_request"]
# after_request = ["ujwal_industries.utils.after_request"]

# Job Events
# ----------
# before_job = ["ujwal_industries.utils.before_job"]
# after_job = ["ujwal_industries.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"ujwal_industries.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Standard Queries
# ----------------
standard_queries = {
	"Supplier": "ujwal_industries.api.approved_supplier_only.supplier_query"
}

# Fixtures
# --------
fixtures = [
	{
		"doctype": "Workflow",
		"filters": [
			[
				"name",
				"in",
				(
					"Purchase Order Approval",
					"Supplier Approval",
					"Material Request Approval",
				),
			]
		],
	},
	{
		"doctype": "Workspace",
		"filters": [
			[
				"name",
				"in",
				(
					"Purchase",
					"Sales",
					"Manufacturing"
				),
			]
		]
	},
	{
		"doctype": "Role",
		"filters": [
			[
				"name",
				"in",
				(
					"Store Manager",
					"Sales Executive"
				),
			]
		],
	},
]

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# =============================================================================
# Apply Custom Batch Size Overrides
# =============================================================================
# Import and apply monkey patches for custom_batchsize field
# These must be at the end to ensure all ERPNext modules are loaded first
from ujwal_industries.overrides.work_order import apply_work_order_overrides
from ujwal_industries.overrides.bom import apply_bom_overrides

apply_work_order_overrides()
apply_bom_overrides()
