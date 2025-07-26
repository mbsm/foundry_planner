from datetime import datetime, timedelta
from collections import defaultdict
from prettytable import PrettyTable

def print_weekly_report(full_plan: dict, orders: list, resources):
    # Step 1: Build week buckets from ResourceManager usage
    all_dates = set(resources.flask_pool.keys())
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

    # Step 2: Aggregate order info for display only
    order_due = {o.order_id: o.due_date for o in orders}
    delayed = {o.order_id for o in orders if full_plan[o.order_id]["status"] == "DELAYED"}
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

        for dstr, _ in plan["schedule"].get("sample_end", []):
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
            sample_end_week[oid] = max(w for w in weeks if w <= d)

        if plan["end_date"]:
            d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            finish_week[oid] = max(w for w in weeks if w <= d)

        dd = order_due.get(oid)
        if dd:
            due_week[oid] = max(w for w in weeks if w <= dd)

    # Step 3: Table setup
    labels = [wk.strftime("%b-%d") for wk in weeks]
    tbl = PrettyTable()
    tbl.field_names = ["Order ID"] + labels

    # a) Metal: total consumed in week vs total available
    header_metal = ["Metal"]
    for wk in weeks:
        total_used = sum(resources.daily_pouring.get(wk + timedelta(days=i), 0) for i in range(7))
        business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        total_limit = resources.max_pouring_tons_per_day * business_days
        header_metal.append(f"{total_used:.1f}/{total_limit:.1f}")
    tbl.add_row(header_metal)

    # b) Molds: total produced in week vs total capacity
    header_molds = ["Molds"]
    for wk in weeks:
        total_used = sum(resources.daily_molds.get(wk + timedelta(days=i), 0) for i in range(7))
        business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        total_limit = resources.max_molds_per_day * business_days
        header_molds.append(f"{total_used}/{total_limit}")
    tbl.add_row(header_molds)

    # c) Flasks: max in use during week vs available (per size)
    for size, limit in resources.flask_limits.items():
        row = [f"Flasks {size.value}"]
        for wk in weeks:
            max_used = max(resources.flask_pool[wk + timedelta(days=i)][size] for i in range(7))
            row.append(f"{max_used}/{limit}")
        tbl.add_row(row)

    # d) Pattern slots: max in use during week vs available
    header_pattern = ["Pattern"]
    for wk in weeks:
        max_used = max(resources.pattern_slots.get(wk + timedelta(days=i), 0) for i in range(7))
        total_limit = resources.max_patterns_per_day
        header_pattern.append(f"{max_used}/{total_limit}")
    tbl.add_row(header_pattern)

    # Weekly production mix for each product family
    for family, max_mix in resources.product_family_max_mix.items():
        row = [f"Mix {family}"]
        for wk in weeks:
            business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
            weekly_used = sum(resources.product_family_usage[wk + timedelta(days=i)].get(family, 0) for i in range(7))
            weekly_max = resources.max_molds_per_day * business_days
            percent = (weekly_used / weekly_max) if weekly_max > 0 else 0
            row.append(f"{int(percent*100)}%/{int(max_mix*100)}%")
        tbl.add_row(row)

    # Data rows for orders (from plan, for display only)
    for oid in full_plan:
        # Get strategy from the order object
        order_obj = next(o for o in orders if o.order_id == oid)
        strategy = order_obj.strategy.name if hasattr(order_obj.strategy, "name") else str(order_obj.strategy)
        disp = f"{oid} ({strategy})"
        if oid in delayed:
            disp = f"\033[93m{disp}\033[0m"
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
    print("Format: metal/molds show total used in week vs total weekly limit. Flasks/patterns show max used in any day of week vs available limit.\n")


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

def print_weekly_resource_usage_report(resources):
    from prettytable import PrettyTable
    from datetime import timedelta

    # Build week buckets
    all_dates = set(resources.flask_pool.keys())
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

    labels = [wk.strftime("%b-%d") for wk in weeks]
    tbl = PrettyTable()
    tbl.field_names = ["Resource"] + labels

    # Metal (pouring)
    header_metal = ["Metal Used"]
    for wk in weeks:
        bd = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        max_used = max(resources.daily_pouring.get(wk + timedelta(days=i), 0) for i in range(7))
        header_metal.append(f"{max_used:.1f}/{resources.max_pouring_tons_per_day}")
    tbl.add_row(header_metal)

    # Molds
    header_molds = ["Molds Used"]
    for wk in weeks:
        bd = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        max_used = max(resources.daily_molds.get(wk + timedelta(days=i), 0) for i in range(7))
        header_molds.append(f"{max_used}/{resources.max_molds_per_day}")
    tbl.add_row(header_molds)

    # Flasks (per size)
    for size, limit in resources.flask_limits.items():
        row = [f"Flasks {size.value}"]
        for wk in weeks:
            max_used = max(resources.flask_pool[wk + timedelta(days=i)][size] for i in range(7))
            row.append(f"{max_used}/{limit}")
        tbl.add_row(row)

    print("\nWEEKLY RESOURCE USAGE REPORT\n")
    print(tbl)
    print("\nFormat: max used per day in week / daily limit.\n")

def print_daily_resource_usage_report(full_plan: dict, orders: list, resources, start_date, end_date):
    from prettytable import PrettyTable
    from datetime import timedelta

    # Genera la lista de días en el rango
    days = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)

    labels = [d.strftime("%Y-%m-%d") for d in days]
    tbl = PrettyTable()
    tbl.field_names = ["Recurso / Orden"] + labels

    # Metal (pouring)
    row_metal = ["Metal"]
    for d in days:
        used = resources.daily_pouring.get(d, 0)
        row_metal.append(f"{int(used)}/{resources.max_pouring_tons_per_day}")
    tbl.add_row(row_metal)

    # Molds
    row_molds = ["Molds"]
    for d in days:
        used = resources.daily_molds.get(d, 0)
        row_molds.append(f"{used}/{resources.max_molds_per_day}")
    tbl.add_row(row_molds)

    # Flasks (por tamaño)
    for size, limit in resources.flask_limits.items():
        row = [f"Flasks {size.value}"]
        for d in days:
            used = resources.flask_pool[d][size]
            row.append(f"{used}/{limit}")
        tbl.add_row(row)

    # Pattern slots
    row_pattern = ["Pattern"]
    for d in days:
        used = resources.pattern_slots.get(d, 0)
        row_pattern.append(f"{used}/{resources.max_patterns_per_day}")
    tbl.add_row(row_pattern)

    # Información de órdenes por día y por etapa (sin staging)
    stage_names = {
        "pattern": "Pattern",
        "molding": "Molding",
        "pouring": "Pouring",
        "shakeout": "Shakeout",
        "sample_end": "Sample End"
    }

    for oid, plan in full_plan.items():
        order_obj = next((o for o in orders if o.order_id == oid), None)
        strategy = order_obj.strategy.name if hasattr(order_obj.strategy, "name") else str(order_obj.strategy) if order_obj else ""
        disp = f"{oid} ({strategy})"
        # Para cada etapa relevante, agrega una fila (sin staging)
        for phase in ["pattern", "molding", "pouring", "shakeout", "sample_end"]:
            row = [f"{disp} {stage_names.get(phase, phase)}"]
            day_map = defaultdict(str)
            for dstr, cnt in plan["schedule"].get(phase, []):
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
                if start_date <= d <= end_date:
                    day_map[d] = str(cnt)
            for d in days:
                row.append(day_map.get(d, ""))
            tbl.add_row(row)

    # Print
    print("\nDAILY RESOURCE USAGE REPORT\n")
    print(tbl)
    print("\nCada orden muestra una fila por etapa: Pattern, Molding, Pouring, Shakeout, End Sample.\n")

def get_weekly_report_data(full_plan: dict, orders: list, resources):
    # Step 1: Build week buckets from ResourceManager usage
    all_dates = set(resources.flask_pool.keys())
    if not all_dates:
        return {"columns": [], "rows": []}

    start = min(all_dates)
    end = max(all_dates)
    w = start - timedelta(days=start.weekday())
    weeks = []
    while w <= end:
        weeks.append(w)
        w += timedelta(weeks=1)

    # Step 2: Aggregate order info for display only
    order_due = {o.order_id: o.due_date for o in orders}
    delayed = {o.order_id for o in orders if full_plan[o.order_id]["status"] == "DELAYED"}
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

        for dstr, _ in plan["schedule"].get("sample_end", []):
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
            sample_end_week[oid] = max(w for w in weeks if w <= d)

        if plan["end_date"]:
            d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            finish_week[oid] = max(w for w in weeks if w <= d)

        dd = order_due.get(oid)
        if dd:
            due_week[oid] = max(w for w in weeks if w <= dd)

    # Step 3: Table setup
    labels = [wk.strftime("%b-%d") for wk in weeks]
    columns = ["Order ID"] + labels
    rows = []

    # a) Metal: total consumed in week vs total available
    header_metal = ["Metal"]
    for wk in weeks:
        total_used = sum(resources.daily_pouring.get(wk + timedelta(days=i), 0) for i in range(7))
        business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        total_limit = resources.max_pouring_tons_per_day * business_days
        header_metal.append(f"{total_used:.1f}/{total_limit:.1f}")
    rows.append(header_metal)

    # b) Molds: total produced in week vs total capacity
    header_molds = ["Molds"]
    for wk in weeks:
        total_used = sum(resources.daily_molds.get(wk + timedelta(days=i), 0) for i in range(7))
        business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        total_limit = resources.max_molds_per_day * business_days
        header_molds.append(f"{total_used}/{total_limit}")
    rows.append(header_molds)

    # c) Flasks: max in use during week vs available (per size)
    for size, limit in resources.flask_limits.items():
        row = [f"Flasks {size.value}"]
        for wk in weeks:
            max_used = max(resources.flask_pool[wk + timedelta(days=i)][size] for i in range(7))
            row.append(f"{max_used}/{limit}")
        rows.append(row)

    # d) Pattern slots: max in use during week vs available
    header_pattern = ["Pattern"]
    for wk in weeks:
        max_used = max(resources.pattern_slots.get(wk + timedelta(days=i), 0) for i in range(7))
        total_limit = resources.max_patterns_per_day
        header_pattern.append(f"{max_used}/{total_limit}")
    rows.append(header_pattern)

    # Weekly production mix for each product family
    for family, max_mix in resources.product_family_max_mix.items():
        row = [f"Mix {family}"]
        for wk in weeks:
            business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
            weekly_used = sum(resources.product_family_usage[wk + timedelta(days=i)].get(family, 0) for i in range(7))
            weekly_max = resources.max_molds_per_day * business_days
            percent = (weekly_used / weekly_max) if weekly_max > 0 else 0
            row.append(f"{int(percent*100)}%/{int(max_mix*100)}%")
        rows.append(row)

    # Data rows for orders (from plan, for display only)
    for oid in full_plan:
        order_obj = next(o for o in orders if o.order_id == oid)
        strategy = order_obj.strategy.name if hasattr(order_obj.strategy, "name") else str(order_obj.strategy)
        disp = f"{oid} ({strategy})"
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
        rows.append(row)

    # Retorna la estructura para la tabla
    return {
        "columns": columns,
        "rows": rows,
        "legend": "P=pattern, ●=sample end, +=end production, ▲=due date"
    }

def get_weekly_resource_usage_data(resources):
    from datetime import timedelta
    all_dates = set(resources.flask_pool.keys())
    if not all_dates:
        return {"columns": [], "rows": []}

    start = min(all_dates)
    end = max(all_dates)
    w = start - timedelta(days=start.weekday())
    weeks = []
    while w <= end:
        weeks.append(w)
        w += timedelta(weeks=1)

    labels = [wk.strftime("%b-%d") for wk in weeks]
    columns = ["Recurso"] + labels
    rows = []

    # Metal
    header_metal = ["Metal"]
    for wk in weeks:
        total_used = sum(resources.daily_pouring.get(wk + timedelta(days=i), 0) for i in range(7))
        business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        total_limit = resources.max_pouring_tons_per_day * business_days
        header_metal.append(f"{total_used:.1f}/{total_limit:.1f}")
    rows.append(header_metal)

    # Molds
    header_molds = ["Molds"]
    for wk in weeks:
        total_used = sum(resources.daily_molds.get(wk + timedelta(days=i), 0) for i in range(7))
        business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
        total_limit = resources.max_molds_per_day * business_days
        header_molds.append(f"{total_used}/{total_limit}")
    rows.append(header_molds)

    # Flasks por tamaño
    for size, limit in resources.flask_limits.items():
        row = [f"Flasks {size.value}"]
        for wk in weeks:
            max_used = max(resources.flask_pool[wk + timedelta(days=i)][size] for i in range(7))
            row.append(f"{max_used}/{limit}")
        rows.append(row)

    # Patterns
    header_pattern = ["Pattern"]
    for wk in weeks:
        max_used = max(resources.pattern_slots.get(wk + timedelta(days=i), 0) for i in range(7))
        total_limit = resources.max_patterns_per_day
        header_pattern.append(f"{max_used}/{total_limit}")
    rows.append(header_pattern)

    # Mix por familia con restricción
    for family, max_mix in resources.product_family_max_mix.items():
        row = [f"Mix {family}"]
        for wk in weeks:
            business_days = sum(1 for i in range(7) if (wk + timedelta(days=i)).weekday() < 5)
            weekly_used = sum(resources.product_family_usage[wk + timedelta(days=i)].get(family, 0) for i in range(7))
            weekly_max = resources.max_molds_per_day * business_days
            percent = (weekly_used / weekly_max) if weekly_max > 0 else 0
            row.append(f"{int(percent*100)}%/{int(max_mix*100)}%")
        rows.append(row)

    return {"columns": columns, "rows": rows}

def get_weekly_orders_summary_data(full_plan, orders, resources):
    # Copia la lógica de la tabla de órdenes semanal (solo las filas de órdenes)
    from datetime import datetime, timedelta
    all_dates = set(resources.flask_pool.keys())
    if not all_dates:
        return {"columns": [], "rows": []}

    start = min(all_dates)
    end = max(all_dates)
    w = start - timedelta(days=start.weekday())
    weeks = []
    while w <= end:
        weeks.append(w)
        w += timedelta(weeks=1)

    labels = [wk.strftime("%b-%d") for wk in weeks]
    columns = ["Order ID"] + labels
    rows = []

    # --- Procesa las filas de órdenes ---
    pattern_weeks = defaultdict(set)
    sample_end_week = {}
    finish_week = {}
    due_week = {}
    order_weekly = defaultdict(lambda: defaultdict(int))
    order_due = {o.order_id: o.due_date for o in orders}

    for oid, plan in full_plan.items():
        for phase in ("pattern", "molding"):
            for dstr, cnt in plan["schedule"].get(phase, []):
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
                wk = max(w for w in weeks if w <= d)
                if phase == "pattern":
                    pattern_weeks[oid].add(wk)
                else:
                    order_weekly[oid][wk] += cnt

        for dstr, _ in plan["schedule"].get("sample_end", []):
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
            sample_end_week[oid] = max(w for w in weeks if w <= d)

        if plan["end_date"]:
            d = datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            finish_week[oid] = max(w for w in weeks if w <= d)

        dd = order_due.get(oid)
        if dd:
            due_week[oid] = max(w for w in weeks if w <= dd)

    for oid in full_plan:
        order_obj = next(o for o in orders if o.order_id == oid)
        strategy = order_obj.strategy.name if hasattr(order_obj.strategy, "name") else str(order_obj.strategy)
        disp = f"{oid} ({strategy})"
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
        rows.append(row)

    return {"columns": columns, "rows": rows}
