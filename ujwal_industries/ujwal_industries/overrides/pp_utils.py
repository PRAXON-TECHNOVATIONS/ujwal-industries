# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAttributeAccessIssue=false
"""
Shared utility functions for Production Plan date calculations.
All private helpers and small whitelist utilities used across pp_fg_dates, pp_sfg_dates,
pp_mr_dates, and pp_cascade modules live here.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

import frappe
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, getdate, get_datetime, now_datetime


# ---------------------------------------------------------------------------
# Import-flag helpers
# ---------------------------------------------------------------------------

# Avi
def _skip_during_data_import():
    return (
        frappe.flags.get("in_import")
        or frappe.flags.get("importing_doctype") == "Production Plan"
    )
# AVI

def _get_allow_backdated_setting() -> bool:
    """
    Get the allow_backdated_planned_start_date setting from Manufacturing Settings.

    Returns:
        True if backdated dates are allowed (default), False otherwise.
    """
    allow_backdated = frappe.db.get_single_value(
        "Manufacturing Settings", "allow_backdated_planned_start_date"
    )
    # Default to True if field doesn't exist yet
    return bool(allow_backdated) if allow_backdated is not None else True


def _adjust_date_if_backdated(date_value: datetime | None) -> datetime | None:
    """
    Adjust the date to today if backdated dates are not allowed and the date is in the past.

    Args:
        date_value: The calculated date (datetime or None)

    Returns:
        The original date if backdated dates are allowed or date is not in past,
        otherwise returns now_datetime() (today's datetime).
    """
    if date_value is None:
        return None

    if _get_allow_backdated_setting():
        return date_value

    today = getdate()
    date_only = getdate(date_value)

    if date_only < today:
        return now_datetime()

    return date_value


def _should_override_planned_date(
    current_date: datetime | None, calculated_date: datetime | None
) -> bool:
    """
    Determine if we should override the current planned_start_date.

    Returns True if:
    - current_date is None (no date set)
    - current_date appears to be auto-set by ERPNext (today's date, close to now)

    Returns False if:
    - current_date appears to be manually set by user (different day or matches calculated)

    Args:
        current_date: Current planned_start_date value
        calculated_date: Our calculated date based on delivery_date - lead_time

    Returns:
        True if we should set/override the date
    """
    if not current_date:
        return True

    if not calculated_date:
        return False

    current_date_obj = getdate(current_date)
    today = getdate(now_datetime())

    # If current date is today, check whether it was auto-set by ERPNext or manually set.
    # ERPNext sets planned_start_date = now_datetime() when creating po_item rows.
    # We detect this by checking if the current value is within 5 minutes of now_datetime().
    # If it is → auto-set → override with our calculation.
    # If it isn't → user manually entered a date on today → preserve it.
    if current_date_obj == today:
        now = now_datetime()
        current_dt = get_datetime(current_date)
        seconds_from_now = abs((now - current_dt).total_seconds())
        if seconds_from_now <= 300:  # within 5 minutes → ERPNext auto-set
            return True
        # User chose today manually — still override only if calculated differs
        calculated_date_obj = getdate(calculated_date)
        return current_date_obj != calculated_date_obj

    # Current date is NOT today — assume user set it manually on a different day.
    # Preserve it unless it happens to exactly match the calculated date (no-op).
    return False


# ---------------------------------------------------------------------------
# Date conversion helpers
# ---------------------------------------------------------------------------

def _to_datetime(date_value: Any) -> datetime:
    """
    Convert Date to Datetime at start of day (00:00:00).

    Args:
        date_value: Date object or string

    Returns:
        Datetime object set to start of day
    """
    if not date_value:
        return now_datetime()

    date_obj = getdate(date_value)
    return datetime.combine(date_obj, datetime.min.time())


def _subtract_minutes_from_datetime(dt: Any, minutes: float) -> datetime:
    """
    Subtract minutes from a datetime.

    Args:
        dt: Datetime object or string
        minutes: Minutes to subtract

    Returns:
        Datetime object with minutes subtracted
    """
    if not dt:
        return now_datetime()

    dt_obj = get_datetime(dt)
    return dt_obj - timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Batch-fetch helpers (FG / po_items)
# ---------------------------------------------------------------------------

def _batch_fetch_delivery_dates(doc: Document, combine_items: bool) -> dict[str, Any]:
    """
    Batch fetch all delivery dates.

    Performance: 1-2 queries total regardless of number of items.

    Args:
        doc: Production Plan document
        combine_items: Whether items are combined by BOM

    Returns:
        Delivery date cache dict
    """
    delivery_cache: dict[str, Any] = {}

    if combine_items:
        # When combine_items is True, get all items from the Sales Orders in sales_orders table
        # Find MIN delivery date per item_code across all SO items
        ref_data = frappe.db.sql(
            """
            SELECT
                soi.item_code,
                MIN(COALESCE(soi.delivery_date, so.delivery_date)) as delivery_date
            FROM `tabProduction Plan Sales Order` ppso
            INNER JOIN `tabSales Order` so ON so.name = ppso.sales_order
            INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
            WHERE ppso.parent = %s AND ppso.parenttype = 'Production Plan'
            GROUP BY soi.item_code
        """,
            (doc.name,),
            as_dict=True,
        )

        # Build cache by item_code (since combine_items groups by item_code/BOM)
        for row in ref_data:
            delivery_cache[row.item_code] = row.delivery_date

    else:
        # Batch fetch SO Item delivery dates
        po_items_list: list[Any] = list(doc.get("po_items") or [])
        so_items = [pi.sales_order_item for pi in po_items_list if pi.sales_order_item]

        if so_items:
            so_item_data = frappe.db.sql(
                """
                SELECT soi.name, COALESCE(soi.delivery_date, so.delivery_date) as delivery_date
                FROM `tabSales Order Item` soi
                LEFT JOIN `tabSales Order` so ON so.name = soi.parent
                WHERE soi.name IN %s
            """,
                (so_items,),
                as_dict=True,
            )

            for row in so_item_data:
                delivery_cache[row.name] = row.delivery_date

    return delivery_cache


def _batch_fetch_bom_operations(doc: Document) -> dict[str, list[dict[str, Any]]]:
    """
    Batch fetch all BOM operations for items in the production plan.

    Args:
        doc: Production Plan document

    Returns:
        Dict mapping BOM name to list of operations with time_in_mins and custom_batchsize
    """
    po_items_list = list(doc.get("po_items") or [])
    bom_nos = list(set([pi.bom_no for pi in po_items_list if pi.bom_no]))

    if not bom_nos:
        return {}

    # Fetch all operations for these BOMs in one query
    operations_data = frappe.db.sql(
        """
        SELECT
            parent as bom_no,
            time_in_mins,
            custom_batchsize,
            operation,
            idx
        FROM `tabBOM Operation`
        WHERE parent IN %(bom_nos)s
        ORDER BY parent, idx
    """,
        {"bom_nos": bom_nos},
        as_dict=True,
    )

    # Group by BOM
    bom_operations: dict[str, list[dict[str, Any]]] = {}
    for op in operations_data:
        if op.bom_no not in bom_operations:
            bom_operations[op.bom_no] = []
        bom_operations[op.bom_no].append(op)

    return bom_operations


def _calculate_production_minutes(
    bom_no: str,
    planned_qty: float,
    bom_time_cache: dict[str, list[dict[str, Any]]]
) -> float:
    """
    Calculate production time in minutes based on BOM operations.

    Formula for each operation:
    - time_per_unit = time_in_mins / custom_batchsize
    - total_time_for_operation = time_per_unit × planned_qty
    - Sum all operations

    Args:
        bom_no: BOM number
        planned_qty: Planned quantity to produce
        bom_time_cache: Cache of BOM operations

    Returns:
        Production time in minutes
    """
    if not bom_no or bom_no not in bom_time_cache:
        return 0.0

    operations = bom_time_cache[bom_no]
    if not operations:
        return 0.0

    total_minutes = 0.0

    for op in operations:
        time_in_mins = float(op.get("time_in_mins") or 0)
        custom_batchsize = float(op.get("custom_batchsize") or 1)

        if custom_batchsize <= 0:
            custom_batchsize = 1  # Avoid division by zero

        # Calculate time per unit
        time_per_unit = time_in_mins / custom_batchsize

        # Calculate total time for this operation
        operation_total_time = time_per_unit * planned_qty

        total_minutes += operation_total_time

    return total_minutes


def _get_delivery_date_from_cache(
    po_item: Document, combine_items: bool, cache: dict[str, Any]
) -> Optional[Any]:
    """
    Get delivery date from cache based on combine mode.

    Args:
        po_item: Production Plan Item
        combine_items: Whether items are combined
        cache: Delivery date cache dict

    Returns:
        Delivery date or None
    """
    if combine_items:
        # When combined, cache is keyed by item_code (earliest date for that item)
        return cache.get(po_item.item_code)
    else:
        # When not combined, cache is keyed by sales_order_item (specific SO item)
        return cache.get(po_item.sales_order_item)


# ---------------------------------------------------------------------------
# Batch-fetch helpers (sub-assembly)
# ---------------------------------------------------------------------------

def _batch_fetch_subassembly_bom_operations(doc: Document) -> dict[str, list[dict[str, Any]]]:
    """
    Batch fetch all BOM operations for sub-assembly items in the production plan.

    Args:
        doc: Production Plan document

    Returns:
        Dict mapping BOM name to list of operations with time_in_mins and custom_batchsize
    """
    if not doc.get("sub_assembly_items"):
        return {}

    sub_assembly_list = list(doc.get("sub_assembly_items") or [])
    bom_nos = list(set([item.bom_no for item in sub_assembly_list]))

    if not bom_nos:
        return {}

    # Fetch all operations for these BOMs in one query
    operations_data = frappe.db.sql(
        """
        SELECT
            parent as bom_no,
            time_in_mins,
            custom_batchsize,
            operation,
            idx
        FROM `tabBOM Operation`
        WHERE parent IN %(bom_nos)s
        ORDER BY parent, idx
    """,
        {"bom_nos": bom_nos},
        as_dict=True,
    )

    # Group by BOM
    bom_operations: dict[str, list[dict[str, Any]]] = {}
    for op in operations_data:
        if op.bom_no not in bom_operations:
            bom_operations[op.bom_no] = []
        bom_operations[op.bom_no].append(op)

    return bom_operations


# ---------------------------------------------------------------------------
# Shift-wise backward scheduling helpers
# ---------------------------------------------------------------------------

def _fetch_shift_config() -> dict[str, Any] | None:
    """
    Fetch default shift type details from Manufacturing Settings.

    Returns:
        Dict with shift fields, or None if shift-wise scheduling is disabled
        or the shift type is not configured.

    Notes:
        Custom lunch fields (custom_lunch_start_time, custom_lunch_end_time) are
        fetched separately so that a missing DB column (e.g. bench migrate not yet
        run) does not break the whole scheduling flow — lunch is simply ignored.
    """
    if not frappe.db.get_single_value("Manufacturing Settings", "enable_shift_wise_scheduling"):
        return None

    shift_type = frappe.db.get_single_value("Manufacturing Settings", "default_shift_type")
    if not shift_type:
        return None

    # Fetch standard Shift Type fields (always exist)
    shift_data = frappe.db.get_value(
        "Shift Type",
        shift_type,
        ["start_time", "end_time", "holiday_list"],
        as_dict=True,
    )

    if not shift_data or not shift_data.start_time or not shift_data.end_time:
        return None

    config: dict[str, Any] = dict(shift_data)

    # Fetch custom lunch fields separately — gracefully skip if not yet in DB schema
    try:
        lunch_data = frappe.db.get_value(
            "Shift Type",
            shift_type,
            ["custom_lunch_start_time", "custom_lunch_end_time"],
            as_dict=True,
        )
        if lunch_data:
            config["custom_lunch_start_time"] = lunch_data.get("custom_lunch_start_time")
            config["custom_lunch_end_time"] = lunch_data.get("custom_lunch_end_time")
    except Exception:
        # Custom fields not yet created — proceed without lunch break adjustment
        config["custom_lunch_start_time"] = None
        config["custom_lunch_end_time"] = None

    return config


# ---------------------------------------------------------------------------
# Default 510-min/day shift (used when Manufacturing Settings has no shift configured)
# 10:00 – 19:00 with 30-min lunch (13:00–13:30) = 540 – 30 = 510 net min/day
# ---------------------------------------------------------------------------
_DEFAULT_SHIFT_CONFIG: dict[str, Any] = {
    "start_time": timedelta(hours=10),
    "end_time": timedelta(hours=19),
    "custom_lunch_start_time": timedelta(hours=13),
    "custom_lunch_end_time": timedelta(hours=13, minutes=30),
    "holiday_list": None,
}


def _get_effective_shift_config() -> dict[str, Any]:
    """
    Always returns a valid shift config dict.

    Tries the configured Shift Type from Manufacturing Settings first.
    Falls back to _DEFAULT_SHIFT_CONFIG (510 net min/day, 10:00–19:00 with
    30-min lunch) when shift-wise scheduling is disabled or not configured.

    Use this instead of _fetch_shift_config() everywhere so that scheduling
    is always shift-aware regardless of Manufacturing Settings.
    """
    return _fetch_shift_config() or _DEFAULT_SHIFT_CONFIG


def _get_holiday_set(holiday_list: str | None) -> set[Any]:
    """Return a set of `datetime.date` objects for all dates in the holiday list."""
    if not holiday_list:
        return set()
    rows = frappe.db.get_all("Holiday", filters={"parent": holiday_list}, pluck="holiday_date")
    return set(rows)


def _td_minutes(td: timedelta) -> float:
    """Convert a timedelta to total minutes."""
    return td.total_seconds() / 60


def _as_timedelta(t: Any) -> timedelta | None:
    """
    Coerce a Frappe Time field value (already a timedelta, or an "HH:MM:SS" string)
    to `datetime.timedelta`. Returns None if falsy.
    """
    if not t:
        return None
    if isinstance(t, timedelta):
        return t
    if isinstance(t, str):
        parts = t.split(":")
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        return timedelta(hours=h, minutes=m, seconds=s)
    return None


def _net_working_minutes(
    shift_start: timedelta,
    shift_end: timedelta,
    lunch_start: timedelta | None,
    lunch_end: timedelta | None,
) -> float:
    """Net working minutes per day = shift duration − lunch break duration."""
    total = _td_minutes(shift_end - shift_start)
    if lunch_start and lunch_end and lunch_end > lunch_start:
        total -= _td_minutes(lunch_end - lunch_start)
    return max(total, 0.0)


def _prev_working_date(d: Any, holidays: set[Any]) -> Any:
    """Step back one calendar day, skipping any dates present in `holidays`."""
    prev = getdate(d) - timedelta(days=1)
    while prev in holidays:
        prev -= timedelta(days=1)
    return prev


def _next_working_date(d: Any, holidays: set[Any]) -> Any:
    """Step forward one calendar day, skipping any dates present in `holidays`."""
    nxt = getdate(d) + timedelta(days=1)
    while nxt in holidays:
        nxt += timedelta(days=1)
    return nxt


def _place_start_in_day(
    day_date: Any,
    remaining_mins: float,
    shift_start: timedelta,
    shift_end: timedelta,
    lunch_start: timedelta | None,
    lunch_end: timedelta | None,
) -> datetime:
    """
    Place the production start time within a single working day, going backward.

    Working slots (forward in time):
      [shift_start … lunch_start]  ← before-lunch slot
      [lunch_end   … shift_end  ]  ← after-lunch slot

    We fill from shift_end backward.  If `remaining_mins` fits in the
    after-lunch slot we stay there; otherwise we skip over lunch and
    consume time from the before-lunch slot.
    """
    base = datetime.combine(getdate(day_date), datetime.min.time())
    shift_end_dt = base + shift_end

    if not lunch_start or not lunch_end or lunch_end <= lunch_start:
        # No lunch break — simple backward placement
        return shift_end_dt - timedelta(minutes=remaining_mins)

    after_lunch_mins = _td_minutes(shift_end - lunch_end)

    if remaining_mins <= after_lunch_mins:
        # Fits entirely in the after-lunch slot
        return shift_end_dt - timedelta(minutes=remaining_mins)
    else:
        # Use all of after-lunch, then go into the before-lunch slot
        remaining_mins -= after_lunch_mins
        lunch_start_dt = base + lunch_start
        return lunch_start_dt - timedelta(minutes=remaining_mins)


def _place_finish_in_day(
    day_date: Any,
    remaining_mins: float,
    shift_start: timedelta,
    shift_end: timedelta,
    lunch_start: timedelta | None,
    lunch_end: timedelta | None,
) -> datetime:
    """
    Place the production finish time within a single working day, going forward.

    Working slots (forward in time):
      [shift_start … lunch_start]  ← before-lunch slot
      [lunch_end   … shift_end  ]  ← after-lunch slot

    We fill from shift_start forward.  If `remaining_mins` fits in the
    before-lunch slot we stay there; otherwise we skip over lunch and
    consume time in the after-lunch slot.
    """
    base = datetime.combine(getdate(day_date), datetime.min.time())
    shift_start_dt = base + shift_start

    if not lunch_start or not lunch_end or lunch_end <= lunch_start:
        # No lunch break — simple forward placement from shift_start
        return shift_start_dt + timedelta(minutes=remaining_mins)

    before_lunch_mins = _td_minutes(lunch_start - shift_start)

    if remaining_mins <= before_lunch_mins:
        # Fits entirely in the before-lunch slot
        return shift_start_dt + timedelta(minutes=remaining_mins)
    else:
        # Use all of before-lunch, jump over lunch, then continue after lunch
        remaining_mins -= before_lunch_mins
        lunch_end_dt = base + lunch_end
        return lunch_end_dt + timedelta(minutes=remaining_mins)


def _net_minutes_from_time(
    from_time: timedelta,
    shift_end: timedelta,
    lunch_start: timedelta | None,
    lunch_end: timedelta | None,
) -> float:
    """
    Net working minutes from `from_time` to shift_end within a single day.

    Subtracts any portion of the lunch break that falls entirely after `from_time`.
    If `from_time` is inside the lunch break, the full remaining lunch is excluded.

    Args:
        from_time: Start time as timedelta from midnight (e.g. timedelta(hours=10)).
        shift_end: Shift end time as timedelta from midnight.
        lunch_start: Lunch start (or None if no lunch).
        lunch_end: Lunch end (or None if no lunch).

    Returns:
        Net working minutes available from from_time to shift_end.
    """
    if from_time >= shift_end:
        return 0.0

    total = _td_minutes(shift_end - from_time)

    if lunch_start and lunch_end and lunch_end > lunch_start:
        # Subtract only the portion of lunch that lies within [from_time, shift_end]
        overlap_start = max(from_time, lunch_start)
        overlap_end = min(lunch_end, shift_end)
        if overlap_end > overlap_start:
            total -= _td_minutes(overlap_end - overlap_start)

    return max(total, 0.0)


def _place_finish_from_time(
    day_date: Any,
    from_time: timedelta,
    remaining_mins: float,
    shift_end: timedelta,
    lunch_start: timedelta | None,
    lunch_end: timedelta | None,
) -> datetime:
    """
    Place finish time starting from `from_time` within a day, going forward.

    Similar to `_place_finish_in_day` but starts from an arbitrary `from_time`
    instead of always from shift_start.  Handles lunch correctly whether
    `from_time` is before, inside, or after lunch.

    Args:
        day_date: The working date.
        from_time: Elapsed time from midnight at which production resumes.
        remaining_mins: Net working minutes left to schedule.
        shift_end: Shift end time as timedelta from midnight.
        lunch_start: Lunch start (or None).
        lunch_end: Lunch end (or None).

    Returns:
        Finish datetime.
    """
    base = datetime.combine(getdate(day_date), datetime.min.time())
    from_dt = base + from_time

    if not lunch_start or not lunch_end or lunch_end <= lunch_start:
        # No lunch break — simple forward addition
        return from_dt + timedelta(minutes=remaining_mins)

    if from_time < lunch_start:
        # We are before lunch: fill before-lunch then jump over lunch if needed
        before_lunch_mins = _td_minutes(lunch_start - from_time)
        if remaining_mins <= before_lunch_mins:
            return from_dt + timedelta(minutes=remaining_mins)
        remaining_mins -= before_lunch_mins
        lunch_end_dt = base + lunch_end
        return lunch_end_dt + timedelta(minutes=remaining_mins)

    if from_time < lunch_end:
        # We are inside the lunch break — resume only after lunch ends
        lunch_end_dt = base + lunch_end
        return lunch_end_dt + timedelta(minutes=remaining_mins)

    # We are after lunch — simple forward addition from from_dt
    return from_dt + timedelta(minutes=remaining_mins)


def _backward_schedule(
    deadline_date: Any,
    production_minutes: float,
    shift_config: dict[str, Any],
) -> datetime:
    """
    Core SAP-style backward scheduling engine.

    Counts `production_minutes` of NET working time backward from the
    start-of-shift on `deadline_date` (the item must be ready *before*
    the shift begins on the delivery day).  Holidays defined in the
    Shift Type's holiday list are skipped.

    Args:
        deadline_date: Delivery date (item ready before shift_start of this date).
        production_minutes: Total production working-minutes required.
        shift_config: Dict returned by `_fetch_shift_config()`.

    Returns:
        Planned start datetime.
    """
    shift_start = _as_timedelta(shift_config.get("start_time"))
    shift_end   = _as_timedelta(shift_config.get("end_time"))
    lunch_start = _as_timedelta(shift_config.get("custom_lunch_start_time"))
    lunch_end   = _as_timedelta(shift_config.get("custom_lunch_end_time"))

    if not shift_start or not shift_end:
        # Incomplete config — fall back to simple subtraction
        return _to_datetime(deadline_date) - timedelta(minutes=production_minutes)

    holidays = _get_holiday_set(shift_config.get("holiday_list"))
    working_mins = _net_working_minutes(shift_start, shift_end, lunch_start, lunch_end)

    if working_mins <= 0:
        return _to_datetime(deadline_date) - timedelta(minutes=production_minutes)

    remaining    = float(production_minutes)
    current_date = getdate(deadline_date)

    while remaining > 0:
        current_date = _prev_working_date(current_date, holidays)

        if remaining < working_mins:
            # Partially fills this day — place the exact start time
            return _place_start_in_day(
                current_date, remaining, shift_start, shift_end, lunch_start, lunch_end
            )
        else:
            remaining -= working_mins
            if remaining <= 0:
                # Exactly fills this day — start at shift_start
                return datetime.combine(getdate(current_date), datetime.min.time()) + shift_start

    # production_minutes == 0 edge-case (loop never entered)
    return _to_datetime(deadline_date)


# ---------------------------------------------------------------------------
# Shift-aware "start now" helper
# ---------------------------------------------------------------------------

def _current_shift_datetime(shift_config: dict[str, Any]) -> datetime:
    """
    Return the earliest datetime from which production can start right now,
    clamped to working hours.

    Rules (evaluated against current time):
      1. Before shift_start today        → today @ shift_start
      2. In lunch break                   → today @ lunch_end
      3. After shift_end today            → next working day @ shift_start
      4. Within working hours             → now_datetime()

    Args:
        shift_config: Dict from _fetch_shift_config().

    Returns:
        Datetime within working hours on the nearest available working day.
    """
    shift_start = _as_timedelta(shift_config.get("start_time"))
    shift_end   = _as_timedelta(shift_config.get("end_time"))
    lunch_start = _as_timedelta(shift_config.get("custom_lunch_start_time"))
    lunch_end   = _as_timedelta(shift_config.get("custom_lunch_end_time"))
    holiday_list = shift_config.get("holiday_list")

    if not shift_start or not shift_end:
        return now_datetime()

    holidays = _get_holiday_set(holiday_list)
    now = now_datetime()
    today = getdate(now)
    base = datetime.combine(today, datetime.min.time())

    # Time-of-day as a timedelta from midnight
    time_of_day = timedelta(
        hours=now.hour,
        minutes=now.minute,
        seconds=now.second,
    )

    if time_of_day < shift_start:
        # Before shift starts — use today's shift_start (if today is a working day)
        if today not in holidays:
            return base + shift_start
        # Today is a holiday — use next working day
        next_day = _next_working_date(today, holidays)
        return datetime.combine(next_day, datetime.min.time()) + shift_start

    if time_of_day >= shift_end:
        # After shift ends — use next working day's shift_start
        next_day = _next_working_date(today, holidays)
        return datetime.combine(next_day, datetime.min.time()) + shift_start

    if lunch_start and lunch_end and lunch_start <= time_of_day < lunch_end:
        # In lunch break — resume at lunch_end
        return base + lunch_end

    # Within working hours — start now (truncate microseconds for cleanliness)
    return now.replace(microsecond=0)


# ---------------------------------------------------------------------------
# Public shift-aware scheduling functions
# ---------------------------------------------------------------------------

def get_adjusted_inhouse_start_date(delivery_date: datetime, production_minutes: float) -> datetime:
    """
    Backward-schedule an In-House item.

    The item must be ready before the shift starts on `delivery_date`.
    Counts `production_minutes` of net working time backward, skipping
    lunch breaks and holidays defined in the Shift Type.

    When backdated dates are not allowed and the calculated start is in the
    past, returns the nearest valid working time (shift-clamped) instead of
    raw now_datetime().

    Falls back to simple calendar-minute subtraction when shift-wise
    scheduling is disabled or the shift is not configured.

    Args:
        delivery_date: Delivery datetime (date part used; item due at shift_start of this date).
        production_minutes: Total production time in working minutes.

    Returns:
        Planned start datetime.
    """
    if production_minutes <= 0:
        return delivery_date

    # Always use shift-aware scheduling (falls back to 510 min/day default)
    shift_config = _get_effective_shift_config()
    result = _backward_schedule(delivery_date, production_minutes, shift_config)

    # If result is in the past and backdated is not allowed, return shift-clamped now
    if not _get_allow_backdated_setting() and getdate(result) < getdate():
        return _current_shift_datetime(shift_config)

    return result


def get_adjusted_subcontract_start_date(
    delivery_date: datetime,
    lead_time_days: int,
    item_code: str = "",
    company: str = "",
) -> datetime:
    """
    Calculate planned_start_date for a Subcontract item.

    Two-step backward calculation:
      1. Subtract `custom_expected_grn_processing_days` (from Item master) as
         working days (shift-aware, holidays skipped) from delivery_date
         → gives the date the subcontractor must deliver (GRN receive date).
      2. Subtract `lead_time_days` as calendar days from the receive date
         → gives planned_start_date (when subcontractor must start).

    When shift-wise scheduling is disabled, GRN days are treated as calendar days.

    Args:
        delivery_date: Delivery datetime.
        lead_time_days: Supplier lead time in calendar days.
        item_code: Item code (to look up GRN processing days).
        company: Company name (unused currently, reserved for future use).

    Returns:
        Planned start datetime (at 00:00:00 of the calculated date).
    """
    del company  # reserved for future company-specific logic

    # --- Step 1: resolve GRN processing days ---
    grn_days = 0
    if item_code:
        grn_days = int(
            frappe.db.get_value("Item", item_code, "custom_expected_grn_processing_days") or 0
        )

    # --- Step 2: receive_date = delivery_date − grn_days (working days) ---
    # Always shift-aware (falls back to 510 min/day default holiday set)
    shift_config = _get_effective_shift_config()
    holidays = _get_holiday_set(shift_config.get("holiday_list"))

    if grn_days > 0:
        receive_date = getdate(delivery_date)
        for _ in range(grn_days):
            receive_date = _prev_working_date(receive_date, holidays)
    else:
        receive_date = getdate(delivery_date)

    # --- Step 3: planned_start_date = receive_date − lead_time_days (calendar) ---
    planned_start = getdate(add_days(receive_date, -lead_time_days))
    return _to_datetime(planned_start)


# ---------------------------------------------------------------------------
# Shift-aware date calculation helpers
# ---------------------------------------------------------------------------

def shift_aware_forward_schedule(
    start_date: datetime,
    production_minutes: float,
    shift_config: dict[str, Any],
) -> datetime:
    """
    Forward-schedule an item based on the current shift.

    Counts `production_minutes` of net working time forward from `start_date`,
    skipping lunch breaks and holidays defined in the Shift Type.

    The start date itself is counted as the first production day: only the
    net working minutes remaining from start_time to shift_end on that day
    are consumed first, then full working days follow.

    Args:
        start_date: Datetime when production begins (may be mid-shift).
        production_minutes: Total production working-minutes required.
        shift_config: Dict returned by `_fetch_shift_config()`.

    Returns:
        Planned finish datetime.
    """
    shift_start = _as_timedelta(shift_config.get("start_time"))
    shift_end   = _as_timedelta(shift_config.get("end_time"))
    lunch_start = _as_timedelta(shift_config.get("custom_lunch_start_time"))
    lunch_end   = _as_timedelta(shift_config.get("custom_lunch_end_time"))

    if not shift_start or not shift_end:
        return start_date + timedelta(minutes=production_minutes)

    holidays = _get_holiday_set(shift_config.get("holiday_list"))
    working_mins = _net_working_minutes(shift_start, shift_end, lunch_start, lunch_end)

    if working_mins <= 0:
        return start_date + timedelta(minutes=production_minutes)

    remaining    = float(production_minutes)
    start_dt     = get_datetime(start_date)
    current_date = getdate(start_dt)

    # ── Step 1: consume available time on the START DATE itself ──────────────
    # Clamp to shift_start if start_dt is before the shift begins.
    start_time_td = timedelta(
        hours=start_dt.hour,
        minutes=start_dt.minute,
        seconds=start_dt.second,
    )
    effective_start = max(start_time_td, shift_start)

    if current_date not in holidays and effective_start < shift_end:
        first_day_mins = _net_minutes_from_time(
            effective_start, shift_end, lunch_start, lunch_end
        )
        if first_day_mins > 0:
            if remaining <= first_day_mins:
                # Finish within the start date
                return _place_finish_from_time(
                    current_date, effective_start, remaining,
                    shift_end, lunch_start, lunch_end
                )
            remaining -= first_day_mins

    # ── Step 2: move through subsequent full working days ────────────────────
    while remaining > 0:
        current_date = _next_working_date(current_date, holidays)

        if remaining <= working_mins:
            # Partially (or exactly) fills this day — place the exact finish time
            return _place_finish_in_day(
                current_date, remaining, shift_start, shift_end, lunch_start, lunch_end
            )
        else:
            remaining -= working_mins

    # production_minutes == 0 edge-case (loop never entered)
    return start_date + timedelta(minutes=production_minutes)


def clamp_to_current_shift(start_date: datetime, shift_config: dict[str, Any]) -> datetime:
    """
    Clamp start_date to the nearest valid working time.

    If start_date is today or in the past, returns the shift-clamped current
    time (via `_current_shift_datetime`).  If start_date is in the future,
    returns it unchanged — it was already placed by backward scheduling.

    Args:
        start_date: The date to clamp.
        shift_config: Dict returned by `_fetch_shift_config()`.

    Returns:
        Clamped datetime within working hours on the nearest working day.
    """
    if getdate(start_date) <= getdate():
        return _current_shift_datetime(shift_config)
    return start_date


def recalculate_finish_date(
    start_date: datetime,
    production_minutes: float,
    shift_config: dict[str, Any] | None,
) -> datetime:
    """
    Recalculate the finish date based on the given start date and production minutes.

    Args:
        start_date: The start date.
        production_minutes: Total production working-minutes required.
        shift_config: Dict returned by `_fetch_shift_config()`, or None.

    Returns:
        Recalculated finish datetime.
    """
    if not shift_config or production_minutes <= 0:
        return start_date + timedelta(minutes=production_minutes)
    return shift_aware_forward_schedule(start_date, production_minutes, shift_config)


def get_holiday_adjusted_date(
    date: Any,
    days: int,
    holiday_list: str | None,
) -> Any:
    """
    Advance `date` by `days` working days, skipping any dates in `holiday_list`.

    After all days are added, the result is pushed forward (one day at a time)
    until it no longer falls on a holiday.  This ensures the final date is
    always a working day even when ``days`` is 0.

    Use-cases:
      - Forward-scheduling GRN Processing Time for Subcontract items.
      - Any calendar arithmetic that must honour the holiday list.

    Args:
        date: Starting date (``datetime.date``, ``datetime.datetime``, or ISO string).
        days: Number of working days to advance (0 = only push off holidays).
        holiday_list: Frappe Holiday List name.  ``None`` treats every calendar
                      day as a working day.

    Returns:
        ``datetime.date`` that is guaranteed to not be in the holiday list.
    """
    holidays = _get_holiday_set(holiday_list)
    current = getdate(date)

    remaining = int(days)
    while remaining > 0:
        current += timedelta(days=1)
        while current in holidays:
            current += timedelta(days=1)
        remaining -= 1

    # Ensure the result itself is not a holiday (handles days=0 case too)
    while current in holidays:
        current += timedelta(days=1)

    return current


# ---------------------------------------------------------------------------
# Supplier / lead-time helpers (private)
# ---------------------------------------------------------------------------

def _get_supplier_lead_time(item_code: str, supplier: str, company: str) -> int:
    """
    Return lead_time_days for a specific supplier of an item (from Item Subcontracting Supplier).

    Args:
        item_code: Item code.
        supplier: Supplier name.
        company: Company name (reserved, unused).

    Returns:
        Lead time in days (0 if not found).
    """
    del company  # reserved for future company-specific filtering
    lead_time = frappe.db.get_value(
        "Item Subcontracting Supplier",
        {"parent": item_code, "supplier": supplier},
        "lead_time_days",
    )
    return int(lead_time or 0)


def _build_parent_chain(doc: Document, changed_item: str) -> list[dict[str, Any]]:
    """
    Build the chain of parent SFG items above `changed_item` in sub_assembly_items.

    For each ancestor, records its manufacturing type and lead time (for Subcontract)
    so callers can sum up total lead time to the FG level.

    Args:
        doc: Production Plan document.
        changed_item: The item_code whose ancestors we want.

    Returns:
        List of dicts (nearest parent first) with keys:
            - item: production_item of the ancestor
            - type: type_of_manufacturing ("In House" / "Subcontract")
            - lead_time: lead time days (0 for In House)
    """
    chain: list[dict[str, Any]] = []
    current_item = changed_item

    while True:
        parent_row = None
        for row in (doc.get("sub_assembly_items") or []):
            if row.production_item == current_item:
                continue
            # Check if current_item is a child in this row's BOM
            if frappe.db.exists("BOM Item", {"parent": row.bom_no, "item_code": current_item}):
                parent_row = row
                break

        if not parent_row:
            break

        lead_time = 0
        if parent_row.type_of_manufacturing == "Subcontract" and parent_row.supplier:
            lead_time = _get_supplier_lead_time(
                parent_row.production_item, parent_row.supplier, doc.company
            )

        chain.append({
            "item": parent_row.production_item,
            "type": parent_row.type_of_manufacturing,
            "lead_time": lead_time,
        })
        current_item = parent_row.production_item

    return chain


# ---------------------------------------------------------------------------
# Whitelist utilities (called from JS via frappe.call)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_subcontract_lead_time(item_code: str, supplier: str | None, company: str) -> int:
    """
    Return lead_time_days for a subcontract item.

    If `supplier` is provided, fetches lead time for that specific supplier.
    Otherwise fetches the default supplier's lead time.

    Returns int (0 if not found).
    """
    filters: dict[str, Any] = {"parent": item_code}
    if supplier:
        filters["supplier"] = supplier
    else:
        filters["is_default"] = 1

    lead_time = frappe.db.get_value(
        "Item Subcontracting Supplier", filters, "lead_time_days"
    )
    return int(lead_time or 0)


@frappe.whitelist()
def get_production_time(bom_no: str, qty: float) -> float:
    """
    Return total production time in minutes for `qty` units of a BOM.

    Formula per operation: (time_in_mins / custom_batchsize) × qty.

    Returns float minutes (0.0 if BOM has no operations).
    """
    if not bom_no:
        return 0.0

    operations = frappe.db.sql(
        """
        SELECT time_in_mins, custom_batchsize
        FROM `tabBOM Operation`
        WHERE parent = %(bom_no)s
        ORDER BY idx
    """,
        {"bom_no": bom_no},
        as_dict=True,
    )

    qty = float(qty or 1.0)
    total_minutes = 0.0
    for op in operations:
        time_in_mins = float(op.get("time_in_mins") or 0)
        batchsize = float(op.get("custom_batchsize") or 1)
        if batchsize <= 0:
            batchsize = 1
        total_minutes += (time_in_mins / batchsize) * qty

    return total_minutes


@frappe.whitelist()
def get_item_default_warehouse(item_code: str, company: str) -> str | None:
    """
    Return the default warehouse for an item in the given company (from Item Default).

    Returns warehouse name string, or None if not configured.
    """
    warehouse = frappe.db.get_value(
        "Item Default",
        {"parent": item_code, "company": company},
        "default_warehouse",
    )
    return warehouse or None


@frappe.whitelist()
def get_supplier_lead_time(item_code: str, supplier: str, company: str) -> dict[str, Any]:
    """
    Return lead_time_days for a supplier of an item.

    Returns dict: {"lead_time_days": N}
    """
    del company  # reserved
    lead_time = frappe.db.get_value(
        "Item Subcontracting Supplier",
        {"parent": item_code, "supplier": supplier},
        "lead_time_days",
    )
    return {"lead_time_days": int(lead_time or 0)}


@frappe.whitelist()
def calculate_production_time_from_bom(bom_no: str) -> dict[str, Any]:
    """
    Return total production time in minutes for a BOM (uses BOM's own quantity).

    Returns dict: {"production_minutes": N}
    """
    if not bom_no:
        return {"production_minutes": 0.0}

    bom_qty = float(frappe.db.get_value("BOM", bom_no, "quantity") or 1.0)

    operations = frappe.db.sql(
        """
        SELECT time_in_mins, custom_batchsize
        FROM `tabBOM Operation`
        WHERE parent = %(bom_no)s
        ORDER BY idx
    """,
        {"bom_no": bom_no},
        as_dict=True,
    )

    total_minutes = 0.0
    for op in operations:
        time_in_mins = float(op.get("time_in_mins") or 0)
        batchsize = float(op.get("custom_batchsize") or 1)
        if batchsize <= 0:
            batchsize = 1
        total_minutes += (time_in_mins / batchsize) * bom_qty

    return {"production_minutes": total_minutes}
