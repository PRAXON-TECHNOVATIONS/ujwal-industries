# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Sales Order Tracker API
Provides list view, detail, and overview summary for the Sales Order Tracker dashboard.
"""

import math
from datetime import timedelta

import frappe
from frappe.utils import nowdate, flt, getdate

from ujwal_industries.api.owner_dashboard import (
    get_so_timeline_detail as get_so_detail,
    get_wo_timeline_detail as get_wo_detail,
)


# ─────────────────────────────────────────────────────────────────────────────
#  INTERNAL IMPLEMENTATION
# ─────────────────────────────────────────────────────────────────────────────

def _compute_so_list(from_date=None, to_date=None, include_completed=False):
    """
    Core SO list with per-SO delay prediction and 5-stage pipeline.

    Priority labels:
      OVERDUE       – delivery date already passed and not fully produced
      DELIVERY RISK – predicted to finish after delivery date
      ON HOLD       – at least one Job Card is On Hold
      ON TRACK      – all good
    """
    today_date = getdate(nowdate())

    # ── 1. Active SOs ────────────────────────────────────────────────────
    date_cond = ""
    params = {}
    if from_date:
        date_cond += " AND so.delivery_date >= %(from_date)s"
        params["from_date"] = from_date
    if to_date:
        date_cond += " AND so.delivery_date <= %(to_date)s"
        params["to_date"] = to_date

    sales_orders = frappe.db.sql(f"""
        SELECT
            so.name, so.customer, so.customer_name,
            so.delivery_date, so.grand_total, so.status,
            so.per_delivered, so.transaction_date
        FROM `tabSales Order` so
        WHERE so.docstatus = 1
          AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
          AND so.per_delivered < 100
          AND so.delivery_date IS NOT NULL
          {date_cond}
        ORDER BY so.delivery_date ASC
        LIMIT 200
    """, params, as_dict=1)

    if not sales_orders:
        return []

    so_names     = [so.name for so in sales_orders]
    so_names_set = set(so_names)

    # ── 1.5. Production Plans linked to these SOs ────────────────────────
    pp_link_rows = frappe.db.sql("""
        SELECT ppso.sales_order, pp.name AS pp_name
        FROM `tabProduction Plan` pp
        INNER JOIN `tabProduction Plan Sales Order` ppso ON ppso.parent = pp.name
        WHERE ppso.sales_order IN %(so_names)s AND pp.docstatus = 1
    """, {"so_names": tuple(so_names)}, as_dict=1)

    pp_to_so     = {}
    pp_names_all = []
    so_has_pp    = set()
    for row in pp_link_rows:
        so_has_pp.add(row.sales_order)
        if row.pp_name not in pp_to_so:
            pp_to_so[row.pp_name] = row.sales_order
            pp_names_all.append(row.pp_name)

    # ── 2. Work Orders ───────────────────────────────────────────────────
    if pp_names_all:
        wo_where  = "(wo.sales_order IN %(so_names)s OR wo.production_plan IN %(pp_names)s)"
        wo_params = {"so_names": tuple(so_names), "pp_names": tuple(pp_names_all)}
    else:
        wo_where  = "wo.sales_order IN %(so_names)s"
        wo_params = {"so_names": tuple(so_names)}

    wo_rows = frappe.db.sql(f"""
        SELECT
            wo.sales_order, wo.production_plan, wo.name,
            wo.status, wo.production_item, wo.qty, wo.produced_qty,
            wo.planned_start_date, wo.planned_end_date,
            wo.actual_start_date, wo.actual_end_date
        FROM `tabWork Order` wo
        WHERE {wo_where} AND wo.docstatus != 2
    """, wo_params, as_dict=1)

    wos_by_so = {}
    seen_wo   = set()
    for w in wo_rows:
        if w.name in seen_wo:
            continue
        so_name = (
            w.sales_order if (w.sales_order and w.sales_order in so_names_set)
            else pp_to_so.get(w.production_plan)
        )
        if so_name and so_name in so_names_set:
            seen_wo.add(w.name)
            wos_by_so.setdefault(so_name, []).append(w)

    # ── 3a. JC counts + on-hold flag per WO ─────────────────────────────
    all_wo_names   = list(seen_wo)
    jc_counts_by_wo = {}
    if all_wo_names:
        jc_rows = frappe.db.sql("""
            SELECT work_order,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='Completed' THEN 1 ELSE 0 END) AS done,
                   SUM(CASE WHEN status='On Hold'   THEN 1 ELSE 0 END) AS on_hold
            FROM `tabJob Card`
            WHERE work_order IN %(wn)s AND docstatus != 2
            GROUP BY work_order
        """, {"wn": tuple(all_wo_names)}, as_dict=1)
        for jc in jc_rows:
            jc_counts_by_wo[jc.work_order] = {
                "total":   int(jc.total),
                "done":    int(jc.done),
                "on_hold": int(jc.on_hold),
            }

    # ── 3. SO items ──────────────────────────────────────────────────────
    item_rows = frappe.db.sql("""
        SELECT parent, item_code, item_name, qty
        FROM `tabSales Order Item`
        WHERE parent IN %(so_names)s
        ORDER BY parent, idx
    """, {"so_names": tuple(so_names)}, as_dict=1)

    items_by_so    = {}
    fg_items_by_so = {}
    for it in item_rows:
        items_by_so.setdefault(it.parent, []).append(it)
        fg_items_by_so.setdefault(it.parent, set()).add(it.item_code)

    # ── 4. Per-SO metrics ────────────────────────────────────────────────
    result = []
    for so in sales_orders:
        delivery_dt = getdate(so.delivery_date)
        wo_list     = wos_by_so.get(so.name, [])
        so_items    = items_by_so.get(so.name, [])

        total_qty     = sum(flt(w.qty) for w in wo_list)
        total_produced = sum(flt(w.produced_qty) for w in wo_list)
        progress_pct  = round((total_produced / total_qty) * 100) if total_qty > 0 else 0

        planned_end_dates  = [getdate(w.planned_end_date) for w in wo_list if w.planned_end_date]
        planned_completion = max(planned_end_dates) if planned_end_dates else None

        predicted_completion = None
        delay_source = "none"

        for w in wo_list:
            if w.status not in ("In Process", "Not Started"):
                continue
            prod_qty = flt(w.produced_qty)
            rem_qty  = flt(w.qty) - prod_qty
            if rem_qty <= 0:
                continue
            if w.actual_start_date and prod_qty > 0:
                days_elapsed  = max((today_date - getdate(w.actual_start_date)).days, 1)
                daily_rate    = prod_qty / days_elapsed
                days_to_finish = math.ceil(rem_qty / daily_rate)
                wo_predicted  = today_date + timedelta(days=days_to_finish)
                src = "pace"
            elif w.planned_end_date:
                wo_predicted = getdate(w.planned_end_date)
                src = "plan"
            else:
                continue
            if predicted_completion is None or wo_predicted > predicted_completion:
                predicted_completion = wo_predicted
                delay_source = src

        if predicted_completion is None and planned_completion:
            predicted_completion = planned_completion
            delay_source = "plan"

        if predicted_completion is None:
            delay_days = (today_date - delivery_dt).days if today_date > delivery_dt else 0
            delay_source = "overdue" if delay_days > 0 else "no_wo"
        else:
            delay_days = (predicted_completion - delivery_dt).days

        actual_overdue = max(0, (today_date - delivery_dt).days)

        # ON HOLD: any WO has a JC on hold
        has_on_hold = any(
            jc_counts_by_wo.get(w.name, {}).get("on_hold", 0) > 0
            for w in wo_list
        )

        # Priority
        if actual_overdue > 0 and progress_pct < 100:
            priority      = "OVERDUE"
            priority_sort = 1000 + actual_overdue
        elif delay_days > 0:
            priority      = "DELIVERY RISK"
            priority_sort = 500 + delay_days
        elif has_on_hold:
            priority      = "ON HOLD"
            priority_sort = 200
        else:
            priority      = "ON TRACK"
            priority_sort = max(0, -delay_days)

        # Items display string
        item_labels = [it.item_name or it.item_code for it in so_items[:2]]
        if len(so_items) > 2:
            item_labels.append(f"+{len(so_items) - 2} more")
        items_display = " · ".join(item_labels)

        # 5-stage pipeline
        fg_items = fg_items_by_so.get(so.name, set())
        fg_wos   = [w for w in wo_list if w.production_item in fg_items]

        jc_total_all = sum(jc_counts_by_wo.get(w.name, {}).get("total", 0) for w in wo_list)
        stage_pp = 1 if so.name in so_has_pp    else 0
        stage_wo = 1 if len(wo_list) > 0        else 0
        stage_jc = 1 if jc_total_all > 0        else 0
        stage_dn = 1 if flt(so.per_delivered) > 0 else 0
        stages_done = 1 + stage_pp + stage_wo + stage_jc + stage_dn

        fg_total_qty    = sum(flt(w.qty) for w in fg_wos)
        fg_produced_qty = sum(flt(w.produced_qty) for w in fg_wos)
        fg_progress_pct = round((fg_produced_qty / fg_total_qty) * 100) if fg_total_qty > 0 else 0

        result.append({
            "name":             so.name,
            "customer":         so.customer,
            "customer_name":    so.customer_name or so.customer,
            "expected_date":    str(delivery_dt),
            "predicted_date":   str(predicted_completion) if predicted_completion else None,
            "delay_days":       delay_days,
            "actual_overdue_days": actual_overdue,
            "progress_pct":     progress_pct,
            "total_qty":        flt(total_qty),
            "produced_qty":     flt(total_produced),
            "wo_count":         len(wo_list),
            "stages_done":      stages_done,
            "stages_total":     5,
            "fg_produced_qty":  fg_produced_qty,
            "fg_total_qty":     fg_total_qty,
            "fg_progress_pct":  fg_progress_pct,
            "value":            flt(so.grand_total),
            "status":           so.status,
            "delay_source":     delay_source,
            "priority":         priority,
            "priority_sort":    priority_sort,
            "items_display":    items_display,
            "has_pp":           so.name in so_has_pp,
        })

    if include_completed:
        c_params = {}
        c_cond = ""
        if from_date:
            c_cond += " AND so.delivery_date >= %(from_date)s"
            c_params["from_date"] = from_date
        if to_date:
            c_cond += " AND so.delivery_date <= %(to_date)s"
            c_params["to_date"] = to_date

        completed_sos = frappe.db.sql(f"""
            SELECT so.name, so.customer, so.customer_name,
                   so.delivery_date, so.grand_total, so.status, so.per_delivered
            FROM `tabSales Order` so
            WHERE so.docstatus = 1
              AND so.status IN ('Completed', 'Closed')
              {c_cond}
            ORDER BY so.delivery_date DESC
            LIMIT 100
        """, c_params, as_dict=1)

        if completed_sos:
            c_names = tuple(so.name for so in completed_sos)
            c_item_rows = frappe.db.sql("""
                SELECT parent, item_code, item_name
                FROM `tabSales Order Item`
                WHERE parent IN %(c)s ORDER BY parent, idx
            """, {"c": c_names}, as_dict=1)
            c_items_by_so = {}
            for it in c_item_rows:
                c_items_by_so.setdefault(it.parent, []).append(it)

            for so in completed_sos:
                its = c_items_by_so.get(so.name, [])
                lbl = [it.item_name or it.item_code for it in its[:2]]
                if len(its) > 2:
                    lbl.append(f"+{len(its)-2} more")
                result.append({
                    "name": so.name, "customer": so.customer,
                    "customer_name": so.customer_name or so.customer,
                    "expected_date": str(getdate(so.delivery_date)) if so.delivery_date else "",
                    "predicted_date": None, "delay_days": 0, "actual_overdue_days": 0,
                    "progress_pct": 100, "total_qty": 0, "produced_qty": 0,
                    "wo_count": 0, "stages_done": 5, "stages_total": 5,
                    "fg_produced_qty": 0, "fg_total_qty": 0, "fg_progress_pct": 100,
                    "value": flt(so.grand_total), "status": so.status,
                    "delay_source": "none", "priority": "COMPLETED", "priority_sort": -1,
                    "items_display": " · ".join(lbl), "has_pp": False,
                })

    result.sort(key=lambda r: -r["priority_sort"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  WHITELIST ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_so_list(from_date=None, to_date=None, include_completed=False):
    """List of active SOs with delay prediction and priority classification."""
    return _compute_so_list(from_date=from_date, to_date=to_date, include_completed=frappe.utils.cint(include_completed))


@frappe.whitelist()
def get_so_overview(from_date=None, to_date=None):
    """
    Summary data for the overview screen:
      - total active SO count + completed count
      - planning breakdown: planned vs not_planned
      - production status breakdown by priority
      - top 5 most overdue SOs
    """
    data = _compute_so_list(from_date=from_date, to_date=to_date)

    # Completed SO count filtered by the same delivery date range
    completed_filters = {"docstatus": 1, "status": ["in", ["Completed", "Closed"]]}
    if from_date and to_date:
        completed_filters["delivery_date"] = ["between", [from_date, to_date]]
    elif from_date:
        completed_filters["delivery_date"] = [">=", from_date]
    elif to_date:
        completed_filters["delivery_date"] = ["<=", to_date]
    completed_count = frappe.db.count("Sales Order", filters=completed_filters)

    planning    = {"planned": 0, "not_planned": 0}
    production  = {"OVERDUE": 0, "DELIVERY RISK": 0, "ON HOLD": 0, "ON TRACK": 0}
    top_overdue = []

    for so in data:
        if so["has_pp"]:
            planning["planned"] += 1
        else:
            planning["not_planned"] += 1

        p = so["priority"]
        if p in production:
            production[p] += 1

        if so["actual_overdue_days"] > 0:
            top_overdue.append({
                "name":          so["name"],
                "customer":      so["customer_name"],
                "overdue_days":  so["actual_overdue_days"],
                "delivery_date": so["expected_date"],
                "value":         so["value"],
                "items_display": so["items_display"],
            })

    top_overdue.sort(key=lambda x: -x["overdue_days"])

    return {
        "total_active":  len(data),
        "completed":     completed_count,
        "planning":      planning,
        "production":    production,
        "top_overdue":   top_overdue[:5],
    }
