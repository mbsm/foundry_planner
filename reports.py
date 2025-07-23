from datetime import datetime, timedelta
from collections import defaultdict
from prettytable import PrettyTable

def print_weekly_report(full_plan: dict, orders: list, pouring_limit_per_day: float, mold_limit_per_day: int, flask_limits: dict):
    # Step 1: Build week buckets
    all_dates = {
        datetime.strptime(d, "%Y-%m-%d").date()
        for plan in full_plan.values()
        for entries in plan["schedule"].values()
        for d, _ in entries
    }
    if not all_dates:
        print("No scheduling data found.")
        return

    start = min(all_dates)
    end = max(all_dates)
    w = start - timedelta(days=start.weekday())
    weeks = []
    while w <= end:
        weeks.append(w)
        w += timedelta(weeks=1)

    # Step 2: Aggregate
    order_due = {o.order_id: o.due_date for o in orders}
    order_flask = {o.order_id: o.flask_size.value for o in orders}
    delayed = {o.order_id for o in orders if full_plan[o.order_id]["status"] == "DELAYED"}

    total_metal = defaultdict(float)
    total_molds = defaultdict(int)
    flask_use = defaultdict(lambda: defaultdict(int))
    pattern_weeks = defaultdict(set)
    sample_end_week = {}
    finish_week = {}
    due_week = {}
    order_weekly = defaultdict(lambda: defaultdict(int))

    for oid, plan in full_plan.items():
        for phase in ("pattern", "molding"):
            for dstr, cnt in plan["schedule"].get(phase, []):
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
                wk = max(w for w in weeks if w <= d)
                if phase == "pattern":
                    pattern_weeks[oid].add(wk)
                else:
                    order_weekly[oid][wk] += cnt
                    total_molds[wk] += cnt
                    flask_use[order_flask[oid]][wk] += cnt

        for dstr, tons in plan["schedule"].get("pouring", []):
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
            wk = max(w for w in weeks if w <= d)
            total_metal[wk] += tons

        # sample_end entries only exist for new orders
        for dstr, _ in plan["schedule"].get("sample_end", []):
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
            sample_end_week[oid] = max(w for w in weeks if w <= d)

        # overall finish
        if plan["end_date"]:
            d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            finish_week[oid] = max(w for w in weeks if w <= d)

        # due date week
        dd = order_due.get(oid)
        if dd:
            due_week[oid] = max(w for w in weeks if w <= dd)

    # Step 3: Table setup
    labels = [wk.strftime("%b-%d") for wk in weeks]
    tbl = PrettyTable()
    tbl.field_names = ["Order ID"] + labels

    # Header rows
    header_metal = ["Metal Used / Limit"]
    header_molds = ["Molds Used / Limit"]
    header_flasks = {
        size: [f"Flasks {size} / Limit ({flask_limits[size]})"]
        for size in flask_limits
    }

    for wk in weeks:
        bd = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        header_metal.append(f"{total_metal.get(wk,0):.1f}/{pouring_limit_per_day*bd:.0f}")
        header_molds.append(f"{total_molds.get(wk,0)}/{mold_limit_per_day*bd}")
        for size in flask_limits:
            used = flask_use[size].get(wk,0)
            header_flasks[size].append(f"{used}/{flask_limits[size]}")

    tbl.add_row(header_metal)
    tbl.add_row(header_molds)
    for row in header_flasks.values():
        tbl.add_row(row)

    # Data rows
    for oid in full_plan:
        disp = f"\033[93m{oid}\033[0m" if oid in delayed else oid
        row = [disp]
        for wk in weeks:
            cnt = order_weekly[oid].get(wk, 0)
            syms = ""
            if wk in pattern_weeks[oid]:
                syms += "P"
            if sample_end_week.get(oid) == wk:
                syms += "●"
            if finish_week.get(oid) == wk:
                syms += "+"
            if due_week.get(oid) == wk:
                syms += "▲"
            if cnt > 0:
                cell = f"{cnt}{syms}"
            elif syms:
                cell = syms
            else:
                cell = ""
            row.append(cell)
        tbl.add_row(row)

    # Print
    print("\nWEEKLY PRODUCTION REPORT\n")
    print(tbl)
    print("\nLegend: 'P'=pattern, '●'=sample end, '+'=end production, '▲'=due date")
    print("Format: molds per week. Top rows show usage vs limit.\n")


def print_schedule_summary(full_plan: dict, orders: list):
    print(f"\n✅ Planning complete for {len(orders)} orders.")

    # Identify delayed and unscheduled
    delayed = []
    unscheduled = []

    for order in orders:
        result = full_plan.get(order.order_id)
        if not result:
            continue
        status = result["status"]
        if status == "DELAYED":
            delayed.append((order.order_id, result["end_date"], order.due_date.isoformat()))
        elif status == "UNSCHEDULED":
            unscheduled.append(order.order_id)

    if delayed:
        print("🟡 Delayed:")
        for order_id, end_date, due_date in delayed:
            print(f"   - {order_id}: finished {end_date}, due {due_date}")
    else:
        print("🟡 Delayed: []")

    if unscheduled:
        print(f"🔴 Unscheduled: {unscheduled}")
    else:
        print("🔴 Unscheduled: []")
