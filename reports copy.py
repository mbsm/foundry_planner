from datetime import datetime, timedelta
from collections import defaultdict

def print_weekly_report(full_plan: dict):
    # Collect all schedule dates
    all_dates = set()
    for plan in full_plan.values():
        for entries in plan["schedule"].values():
            for date_str, _ in entries:
                all_dates.add(datetime.strptime(date_str, "%Y-%m-%d").date())

    if not all_dates:
        print("No scheduling data found.")
        return

    # Determine weekly buckets
    start_date = min(all_dates)
    end_date = max(all_dates)
    current = start_date - timedelta(days=start_date.weekday())  # align to Monday
    weeks = []
    while current <= end_date:
        weeks.append(current)
        current += timedelta(weeks=1)

    # Prepare data per order
    order_weekly = defaultdict(lambda: defaultdict(int))
    finish_week = {}
    due_week = {}

    for order_id, plan in full_plan.items():
        # Molds per week
        for date_str, qty in plan["schedule"].get("molding", []):
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            wk = max(w for w in weeks if w <= d)
            order_weekly[order_id][wk] += qty

        # End date marker
        if plan["end_date"]:
            end_d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            finish_week[order_id] = max(w for w in weeks if w <= end_d)

        # Due date marker (same as end_date in current structure)
        if plan["end_date"]:
            due_d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            due_week[order_id] = max(w for w in weeks if w <= due_d)

    # Print header
    print("\nWEEKLY PRODUCTION REPORT (Molds per Order)\n")
    week_labels = [wk.strftime("%b-%d") for wk in weeks]
    header = ["Order ID"] + week_labels
    print(" | ".join(header))
    print("-" * (len(header) * 12))

    # Print order rows
    for order_id in full_plan:
        row = [order_id]
        for wk in weeks:
            n = order_weekly[order_id].get(wk, 0)
            symbols = ""
            if finish_week.get(order_id) == wk:
                symbols += "+"
            if due_week.get(order_id) == wk:
                symbols += "▲"
            cell = f"{n}{symbols}" if n or symbols else ""
            row.append(cell.ljust(6))
        print(" | ".join(row))

    print("\nLegend: '+' = end of production, '▲' = due date\n")
