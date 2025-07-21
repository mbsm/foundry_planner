from datetime import datetime, timedelta
from collections import defaultdict
from prettytable import PrettyTable

def print_weekly_report(full_plan: dict, orders: list, pouring_limit_per_day: float, mold_limit_per_day: int, flask_limits: dict):
    # Step 1: Generate weekly buckets
    all_dates = set()
    for plan in full_plan.values():
        for entries in plan["schedule"].values():
            for date_str, _ in entries:
                all_dates.add(datetime.strptime(date_str, "%Y-%m-%d").date())
    if not all_dates:
        print("No scheduling data found.")
        return

    start_date = min(all_dates)
    end_date = max(all_dates)
    current = start_date - timedelta(days=start_date.weekday())
    weeks = []
    while current <= end_date:
        weeks.append(current)
        current += timedelta(weeks=1)

    # Step 2: Aggregate usage data
    order_weekly_molds = defaultdict(lambda: defaultdict(int))
    total_metal_weekly = defaultdict(float)
    total_molds_weekly = defaultdict(int)
    flask_usage_weekly = defaultdict(lambda: defaultdict(int))
    finish_week = {}
    due_week = {}

    order_due_map = {o.order_id: o.due_date for o in orders}
    order_flask_map = {o.order_id: o.flask_size.value for o in orders}
    delayed_orders = {
        o.order_id for o in orders
        if full_plan[o.order_id]["status"] == "DELAYED"
    }

    for order_id, plan in full_plan.items():
        flask_type = order_flask_map[order_id]

        for date_str, molds in plan["schedule"].get("molding", []):
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            wk = max(w for w in weeks if w <= d)
            order_weekly_molds[order_id][wk] += molds
            total_molds_weekly[wk] += molds
            flask_usage_weekly[flask_type][wk] += molds

        for date_str, tons in plan["schedule"].get("pouring", []):
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            wk = max(w for w in weeks if w <= d)
            total_metal_weekly[wk] += tons

        if plan["end_date"]:
            end_d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            finish_week[order_id] = max(w for w in weeks if w <= end_d)

        due_d = order_due_map.get(order_id)
        if due_d:
            due_week[order_id] = max(w for w in weeks if w <= due_d)

    def business_days_in_week(start: datetime.date):
        return sum(1 for i in range(7) if (start + timedelta(days=i)).weekday() < 5)

    max_metal_per_week = {wk: pouring_limit_per_day * business_days_in_week(wk) for wk in weeks}
    max_molds_per_week = {wk: mold_limit_per_day * business_days_in_week(wk) for wk in weeks}
    max_flask_per_week = {
        size: {wk: flask_limits[size] * business_days_in_week(wk) for wk in weeks}
        for size in flask_limits
    }

    # Step 3: Setup table
    week_labels = [wk.strftime("%b-%d") for wk in weeks]
    table = PrettyTable()
    table.field_names = ["Order ID"] + week_labels

    # Header rows
    metal_row = ["Metal Used / Limit"]
    mold_row = ["Molds Used / Limit"]
    flask_rows = []

    for size in flask_limits:
        flask_rows.append([f"Flasks {size} / Limit"])

    for wk in weeks:
        metal_row.append(f"{total_metal_weekly.get(wk,0.0):.1f}/{max_metal_per_week[wk]:.0f}")
        mold_row.append(f"{total_molds_weekly.get(wk,0)}/{max_molds_per_week[wk]}")

        for i, size in enumerate(flask_limits):
            used = flask_usage_weekly[size].get(wk, 0)
            limit = max_flask_per_week[size][wk]
            flask_rows[i].append(f"{used}/{limit}")

    table.add_row(metal_row)
    table.add_row(mold_row)
    for flask_row in flask_rows:
        table.add_row(flask_row)

    # ANSI red for delayed orders
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    for order_id in full_plan:
        is_delayed = order_id in delayed_orders
        display_id = f"{YELLOW}{order_id}{RESET}" if is_delayed else order_id
        row = [display_id]

        for wk in weeks:
            molds = order_weekly_molds[order_id].get(wk, 0)
            symbols = ""
            if finish_week.get(order_id) == wk:
                symbols += "+"
            if due_week.get(order_id) == wk:
                symbols += "▲"
            cell = f"{molds}{symbols}" if molds or symbols else ""
            row.append(cell)

        table.add_row(row)

    # Print result
    print("\nWEEKLY PRODUCTION REPORT\n")
    print(table)
    print("\nLegend: '+' = end of production, '▲' = due date")
    print("Format: molds per week. Red = delayed. Top rows show resource usage vs limit.\n")



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
