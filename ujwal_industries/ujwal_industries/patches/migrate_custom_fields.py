# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

from .custom_fields import serial_no, manufacturing_settings


def run_all():
    """Run all custom field migrations"""
    serial_no.create_fields()
    manufacturing_settings.create_fields()
