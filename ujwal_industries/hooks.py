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
app_include_css = [
    "/assets/ujwal_industries/css/custom_modal.css?V=0.1.29",
    "/assets/ujwal_industries/css/list_view_revamp.css?V=0.1.2",
]
app_include_js = [
	"/assets/ujwal_industries/js/custom_dialog.js?V=0.1.29",
	"/assets/ujwal_industries/js/manage_dates_dialog.js?V=0.1.30",
	"/assets/ujwal_industries/js/parallel_manage_dates_dialog.js?V=0.1.40",
	"/assets/ujwal_industries/js/list_view_revamp.js?V=0.1.0",
	# "/assets/ujwal_industries/js/grid_custom_icons.js",
]
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
	"Delivery Note": "public/js/delivery_note.js",
	"Sales Order": "public/js/sales_order.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"Job Card": "public/js/job_card.js",
	"Workstation": "public/js/workstation.js",
 	"Work Order": "public/js/work_order_scrap.js",
  	"Stock Entry": "public/js/stock_entry.js",
	"Production Plan Importer": "public/js/production_plan_importer.js",
	"BOM": "public/js/bom.js",
	"Item": "public/js/item.js",
	"Asset": "public/js/asset.js",
	"Asset Category": "public/js/asset_category.js",
	"Sales Order": "public/js/sales_order_custom.js",
	"Purchase Order": "public/js/purchase_order_custom.js",
	"Purchase Receipt": "public/js/purchase_receipt.js",
}
doctype_tree_js = {
	"Asset Category": "public/js/asset_category_tree.js",
}
doctype_list_js = {
	"Production Plan": "public/js/production_plan_list.js",
}
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

after_install = "ujwal_industries.install.after_install"
after_migrate = ["ujwal_industries.ujwal_industries.patches.migrate_custom_fields.run_all",
                 "ujwal_industries.install.after_install"]

# Uninstallation
# ------------

# before_uninstall = "ujwal_industries.uninstall.before_uninstall"
after_uninstall = "ujwal_industries.ujwal_industries.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "ujwal_industries.utils.before_app_install"
# after_app_install = "ujwal_industries.utils.after_app_install"

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
	"Production Plan": "ujwal_industries.ujwal_industries.overrides.production_plan_class.CustomProductionPlan",
	"Asset Category": "ujwal_industries.ujwal_industries.overrides.asset_category.CustomAssetCategory",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Item": {
		"validate": "ujwal_industries.ujwal_industries.overrides.item.validate_subcontracting_suppliers",
		"autoname": "ujwal_industries.ujwal_industries.overrides.item.autoname",
	},
	"Asset": {
		"autoname": "ujwal_industries.ujwal_industries.overrides.asset.autoname"
	},

	"Customer": {
		"autoname": "ujwal_industries.ujwal_industries.overrides.customer.autoname"
	},

 	"Stock Entry": {
        "before_validate": [
            "ujwal_industries.ujwal_industries.overrides.stock_entry.stash_manually_set_rates"
        ],
        "validate": [
            "ujwal_industries.ujwal_industries.overrides.stock_entry.validate_scrap_item_tolerance",
            "ujwal_industries.ujwal_industries.overrides.stock_entry.protect_manually_set_rates"
        ],
        "before_save": [
            "ujwal_industries.ujwal_industries.overrides.stock_entry.finalize_manual_rate_taxes"
        ]
    },
	"Production Plan": {
		"onload": "ujwal_industries.ujwal_industries.overrides.production_plan.onload_production_plan",
		"validate": [
			"ujwal_industries.ujwal_industries.overrides.production_plan.validate_planned_start_dates",
			# "ujwal_industries.ujwal_industries.overrides.tool_limit.validate_tool_conflict",
			"ujwal_industries.ujwal_industries.overrides.tool_limit.fetched_default_bom",
			# "ujwal_industries.ujwal_industries.overrides.tool_limit.validate_tool_maintenance",
		],
		"before_save": [
			"ujwal_industries.ujwal_industries.overrides.production_plan.set_planned_start_dates",
			"ujwal_industries.ujwal_industries.overrides.production_plan.set_subcontracting_suppliers",
			"ujwal_industries.ujwal_industries.overrides.production_plan.master_set_fg_dates_by_type",
			"ujwal_industries.ujwal_industries.overrides.production_plan.adjust_mr_items_and_propagate",
			# "ujwal_industries.ujwal_industries.overrides.production_plan.set_item_type_in_production_plan",
		]
	},
	"Supplier": {
		"before_save": "ujwal_industries.api.supplier_gstin_check.check_duplicate_gstin",
		"autoname"	 : "ujwal_industries.api.supplier_gstin_check.autoname"
	},
	"Material Request": {
		"before_insert": "ujwal_industries.ujwal_industries.patches.mr_reorder.set_reorder_field",
	},
	"Sales Order": {
		"before_save": [
			"ujwal_industries.ujwal_industries.overrides.position_number_sync.sync_sales_order_position_numbers",
			"ujwal_industries.ujwal_industries.overrides.sales_order_qty_lock.prevent_qty_change_when_production_plan_exists",
		],
		"before_update_after_submit": "ujwal_industries.ujwal_industries.overrides.sales_order_qty_lock.prevent_qty_change_when_production_plan_exists",
	},
	"Delivery Note": {
		"before_save": "ujwal_industries.ujwal_industries.overrides.position_number_sync.sync_delivery_note_position_numbers"
	},
	"Sales Invoice": {
		"before_save": "ujwal_industries.ujwal_industries.overrides.position_number_sync.sync_sales_invoice_position_numbers"
	},
	"Job Card": {
		"onload": "ujwal_industries.ujwal_industries.overrides.job_card.onload_job_card",
		"before_submit": [
			"ujwal_industries.ujwal_industries.overrides.job_card.cascade_complete_previous",
			"ujwal_industries.ujwal_industries.overrides.job_card.override_job_card_qty_validation",
		],
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
        # "before_submit": "ujwal_industries.ujwal_industries.overrides.purchase_receipt.validate_processing_time_before_submit",
        "on_submit" : "ujwal_industries.ujwal_industries.overrides.purchase_receipt.set_actual_processing_time",
        "before_insert" : "ujwal_industries.ujwal_industries.overrides.purchase_receipt.before_insert",
    },
	"Data Import": {
		"validate": "ujwal_industries.ujwal_industries.overrides.data_import.validate_production_plan_import"
	},
	"Work Order":{
		"before_insert": "ujwal_industries.ujwal_industries.overrides.work_order.set_wip_before_insert"
	},
 	"Quality Inspection": {
        "on_submit": "ujwal_industries.ujwal_industries.overrides.quality_inspection.update_grn_processing_time"
    },
	"BOM":{
  		"on_update_after_submit": "ujwal_industries.overrides.bom.validate_default_tool",
		"validate": [
      					"ujwal_industries.overrides.bom.validate_bom",
      					# "ujwal_industries.overrides.bom.validate_change_bom_value",
					],			
		"autoname": "ujwal_industries.overrides.bom.autoname",
		"before_save": "ujwal_industries.overrides.bom.before_save",
		"after_insert": "ujwal_industries.overrides.bom.after_insert",
	},
 	"Asset Maintenance": {
        "before_save": "ujwal_industries.ujwal_industries.overrides.asset_maintenance.set_end_date_from_asset",
    },
	"*": {
        "autoname": "ujwal_industries.api.naming_series.numeric_series"
    },
	
	"Sales Order":{
		"before_insert": "ujwal_industries.ujwal_industries.overrides.sales_order.before_insert",
	},
	"Sales Invoice":{
		"before_insert": "ujwal_industries.ujwal_industries.overrides.sales_invoice.before_insert",
	},
	"Purchase Order":{
		"before_insert": "ujwal_industries.ujwal_industries.overrides.purchase_order.before_insert",
	},
	"Quotation":{
		"before_insert": "ujwal_industries.ujwal_industries.overrides.quotation.before_insert",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"* * * * *": [
			"ujwal_industries.ujwal_industries.overrides.downtime_entry.sync_workstation_statuses"
		]
	},
	"hourly": [
		"ujwal_industries.api.optimized_reorder.optimized_reorder_item"
	],
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
        "ujwal_industries.ujwal_industries.overrides.job_card.make_time_log_with_material_check",
    "erpnext.controllers.accounts_controller.update_child_qty_rate":
        "ujwal_industries.ujwal_industries.overrides.sales_order_update_items.update_child_qty_rate",
}

#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps

override_doctype_dashboards = {

	"Purchase Order" : "ujwal_industries.ujwal_industries.custom_dashboard.update_po_dashboard",
}

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
	# {
	# 	"doctype": "Workflow",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			(
	# 				"Purchase Order Approval",
	# 				"Supplier Approval",
	# 				"Material Request Approval",
	# 				"BOM Approval",
	# 			),
	# 		]
	# 	],
	# },
	# {
	# 	"doctype": "Workspace",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			(
	# 				"Purchase",
	# 				"Sales",
	# 				"Manufacturing"
	# 			),
	# 		]
	# 	]
	# },
	{
		"doctype": "Role",
		"filters": [
			[
				"name",
				"in",
				(
					"Store Manager",
					"Sales Executive"
					"Super Approver",
					"Store Incharge",
					"Outsource Store Manager",
					
				),
			]
		],
	},
	# {
	# 	"doctype": "Notification",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			(
	# 				"BOM Approval - {{doc.name}}",
	# 			),
	# 		]
	# 	],
	# },
	

#  {"dt": "Print Format", "filters": {"module": "Ujwal Industries"}},
#  {"dt": "Property Setter" , "filters":{"module": "Ujwal Industries"}}
]

# Translations
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
