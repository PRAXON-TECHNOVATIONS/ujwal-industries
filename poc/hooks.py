app_name = "poc"
app_title = "Poc"
app_publisher = "Ujjwal Aggrawal"
app_description = "Custom app for POC purpose"
app_email = "ujjmee2279@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "poc",
# 		"logo": "/assets/poc/logo.png",
# 		"title": "Poc",
# 		"route": "/poc",
# 		"has_permission": "poc.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/poc/css/poc.css"
# app_include_js = "/assets/poc/js/poc.js"

# include js, css files in header of web template
# web_include_css = "/assets/poc/css/poc.css"
# web_include_js = "/assets/poc/js/poc.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "poc/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}

doctype_js = {
    "Supplier": "public/js/supplier.js",
    "Supplier Quotation": "public/js/supplier_quotation.js"
}

# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "poc/public/icons.svg"

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
# 	"methods": "poc.utils.jinja_methods",
# 	"filters": "poc.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "poc.install.before_install"
# after_install = "poc.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "poc.uninstall.before_uninstall"
# after_uninstall = "poc.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "poc.utils.before_app_install"
# after_app_install = "poc.utils.after_app_install"
after_migrate = "poc.poc.migrate_custom_fields.run_all"
# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "poc.utils.before_app_uninstall"
# after_app_uninstall = "poc.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "poc.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

doc_events = {
    "Supplier": {
        "before_save": "poc.api.supplier_gstin_check.check_duplicate_gstin"
    }
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"poc.tasks.all"
# 	],
# 	"daily": [
# 		"poc.tasks.daily"
# 	],
# 	"hourly": [
# 		"poc.tasks.hourly"
# 	],
# 	"weekly": [
# 		"poc.tasks.weekly"
# 	],
# 	"monthly": [
# 		"poc.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "poc.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "poc.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "poc.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["poc.utils.before_request"]
# after_request = ["poc.utils.after_request"]

# Job Events
# ----------
# before_job = ["poc.utils.before_job"]
# after_job = ["poc.utils.after_job"]

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
# 	"poc.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
standard_queries = {
    "Supplier": "poc.api.approved_supplier_only.supplier_query"
}

fixtures = [
    {"doctype": "Workflow", "filters": [["name" , "in" , ("Supplier Approval")]]},
] 