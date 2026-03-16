# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

from .custom_fields import manufacturing_setting, serial_no


def run_all():
    """Run all custom field migrations"""
    serial_no.create_fields()
    manufacturing_setting.create_fields()
