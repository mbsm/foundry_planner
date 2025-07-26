from datetime import date, timedelta
from orders_parser import Strategy
from orders_parser import Order
from orders_parser import OrderStatus
from collections import defaultdict
from math import ceil
import logging

def plan_full_order(order, calendar, resources, max_search_days=30, safety_days=3, days_after_pattern=3, days_after_sample=3):
    # For recurrent orders, delegate to plan_order
    if not order.is_new:
        return plan_order(order, calendar, resources, max_search_days=max_search_days, safety_days=safety_days)

    # Initialize plan structure
    plan = {
        "order_id": order.order_id,
        "status": None,
        "start_date": None,
        "end_date": None,
        "schedule": defaultdict(list),
    }

    # Step 1: Pattern Manufacturing (business days)
    today = date.today()
    remaining = order.pattern_days
    ptr = today
    while remaining > 0:
        if calendar.is_business_day(ptr) and resources.can_schedule_pattern(ptr):
            resources.reserve_pattern(ptr)
            plan["schedule"]["pattern"].append((ptr, 1))
            remaining -= 1
        ptr = calendar.next_business_day(ptr)
    pattern_end = plan["schedule"]["pattern"][-1][0]

    # Step 2: Sample Order (ASAP, non-new)
    sample_order = Order(order_id=f"{order.order_id}-SAMPLE")
    sample_order.strategy = Strategy.ASAP
    sample_order.is_new = False
    sample_order.due_date = order.due_date
    sample_order.pattern_days = 0
    sample_order.sample_molds = 0
    sample_order.cooling_days = order.cooling_days
    sample_order.finishing_days_nominal = order.finishing_days_min
    sample_order.finishing_days_min = order.finishing_days_min
    sample_order.parts_total = order.sample_molds * order.parts_per_mold
    sample_order.parts_per_mold = order.parts_per_mold
    sample_order.part_weight_ton = order.part_weight_ton
    sample_order.flask_size = order.flask_size
    sample_order.alloy = order.alloy
    sample_order.total_molds = order.sample_molds

    sample_start = calendar.add_business_days(pattern_end, days_after_pattern)
    sample_plan = plan_order(sample_order, calendar, resources, max_search_days=max_search_days, safety_days=0, start_date=sample_start)
    if sample_plan["status"] == OrderStatus.UNSCHEDULED:
        plan["status"] = OrderStatus.UNSCHEDULED
        return plan

    sample_end = sample_plan["end_date"]
    # Mark sample completion for reporting
    plan["schedule"]["sample_end"].append((sample_end, 1))

    # Step 3: Main Production (after sample finishes)
    # Adjust remaining production
    produced = sample_order.parts_total
    order.parts_total -= produced
    order.total_molds = ceil(order.parts_total / order.parts_per_mold)

    main_start = calendar.add_business_days(sample_end, days_after_sample)
    main_plan = plan_order(order, calendar, resources, max_search_days=max_search_days, safety_days=safety_days, start_date=main_start)
    if main_plan["status"] == OrderStatus.UNSCHEDULED:
        plan["status"] = OrderStatus.UNSCHEDULED
        return plan

    # Step 4: Consolidate schedule and status
    plan["status"] = max(sample_plan["status"], main_plan["status"], key=lambda s: s.value)
    plan["start_date"] = plan["schedule"]["pattern"][0][0]
    plan["end_date"] = max(sample_plan["end_date"], main_plan["end_date"])

    # Merge sample and main phases into plan.schedule
    for phase in ["pattern", "molding", "staging", "pouring", "shakeout", "finishing"]:
        plan["schedule"][phase].extend(sample_plan["schedule"].get(phase, []))
        plan["schedule"][phase].extend(main_plan["schedule"].get(phase, []))

    return plan


def plan_order(order, calendar, resources, max_search_days=30, safety_days=3, start_date=None):
    """
    Plan a single order using the specified strategy (ASAP or JIT).
    """
    from orders_parser import OrderStatus, Strategy

    order_id = order.order_id
    estimated_duration = order.compute_estimated_duration(resources.max_molds_per_day)

    # Determine start date and direction
    if start_date is not None:
        direction = 1 if order.strategy.name == Strategy.ASAP else -1
    else:
        if order.strategy.name == Strategy.JIT:
            start_date = calendar.add_business_days(order.due_date, -(estimated_duration + safety_days))
            direction = -1
        else:
            start_date = date.today()
            direction = 1

    schedule = None
    attempt = 0

    while attempt < max_search_days:
        if not calendar.is_business_day(start_date):
            start_date = calendar.add_business_days(start_date, direction)
            attempt += 1
            continue

        can_schedule, plan = try_schedule(order, start_date, calendar, resources)
        if can_schedule and plan is not None:
            schedule, end_date = firm_schedule(order, start_date, calendar, resources, plan)
            status = OrderStatus.ONTIME if end_date <= order.due_date else OrderStatus.DELAYED
            return {
                "order_id": order_id,
                "status": status,
                "start_date": start_date,
                "end_date": end_date,
                "schedule": schedule
            }

        start_date = calendar.add_business_days(start_date, direction)
        attempt += 1

    # Retry JIT as ASAP if it fails
    if order.strategy.name == Strategy.JIT and schedule is None:
        order.strategy = Strategy.ASAP
        return plan_order(order, calendar, resources,
                          max_search_days=max_search_days, safety_days=0)

    return {
        "order_id": order_id,
        "status": OrderStatus.UNSCHEDULED,
        "start_date": None,
        "end_date": None,
        "schedule": {}
    }

def try_schedule(order, start_date, calendar, resources):
    molds_remaining = order.total_molds
    mold_day = start_date
    daily_plan = []
    schedule = defaultdict(list)
    tons_per_mold = order.parts_per_mold * order.part_weight_ton

    # Pool temporal para los flasks del pedido en curso
    temp_flask_pool = defaultdict(lambda: defaultdict(int))

    while molds_remaining > 0:
        if not calendar.is_business_day(mold_day):
            mold_day = calendar.add_business_days(mold_day, 1)
            continue
        
        #calculate dates for each phase
        staging_day = calendar.add_calendar_days(mold_day, 1)
        if(calendar.is_business_day(staging_day)):
            pouring_day = staging_day
        else:
            pouring_day = calendar.next_business_day(staging_day)
        
        cooling_ends = calendar.add_calendar_days(pouring_day, order.cooling_days)
        if calendar.is_business_day(cooling_ends):
            shakeout_day = cooling_ends
        else:
            shakeout_day = calendar.next_business_day(cooling_ends)
        
        flask_release_day = shakeout_day

        # Calculate the days needed for flasks
        flask_days = []
        d = mold_day
        while d <= flask_release_day:
            flask_days.append(d)
            d = calendar.add_calendar_days(d, 1)

        # Calculate the minimum available considering the temp pool
        max_molds_flasks = float('inf')
        for d in flask_days:
            used = resources.flask_pool[d][order.flask_size] + temp_flask_pool[d][order.flask_size]
            available = resources.flask_limits[order.flask_size] - used
            max_molds_flasks = min(max_molds_flasks, available)

        max_molds_today = resources.compute_available_molds(order, mold_day, pouring_day)
        max_molds_pouring = resources.compute_available_pouring(order, pouring_day)
        max_molds_mix = resources.compute_available_mix(order, mold_day)
        available_today = min(max_molds_today, max_molds_pouring, max_molds_mix, max_molds_flasks, molds_remaining)

        logging.info(
            f"{order.order_id}: Day {mold_day} - "
            f"molds_today={max_molds_today}, pouring={max_molds_pouring}, flasks={max_molds_flasks}, "
            f"remaining={molds_remaining}, available={available_today}"
        )

        if available_today <= 0:
            mold_day = calendar.add_business_days(mold_day, 1)
            continue

        # Reserva en el pool temporal
        for d in flask_days:
            temp_flask_pool[d][order.flask_size] += available_today

        # Plan provisional
        daily_plan.append((mold_day, available_today))
        schedule["molding"].append({
            "mold_day": mold_day, 
            "qty": available_today, 
            "flask_release_day": flask_release_day
        })
        schedule["staging"].append((staging_day, available_today))
        schedule["pouring"].append((pouring_day, round(available_today * tons_per_mold, 3)))
        schedule["shakeout"].append((shakeout_day, available_today))

        molds_remaining -= available_today
        mold_day = calendar.add_business_days(mold_day, 1)

    if molds_remaining > 0 or not daily_plan:
        return False, None

    # Final check: finishing must fit in due date
    last_mold_day = daily_plan[-1][0]
    staging_day = calendar.add_calendar_days(last_mold_day, 1)
    pouring_day = calendar.next_business_day(staging_day)
    cooling_ends = calendar.add_calendar_days(pouring_day, order.cooling_days)
    shakeout_day = calendar.next_business_day(cooling_ends)
    finishing_start = calendar.next_business_day(shakeout_day)

    # Try to fit finishing within allowed window
    for days in range(order.finishing_days_nominal, order.finishing_days_min - 1, -1):
        finishing_end = calendar.add_business_days(finishing_start, days)
        if finishing_end <= order.due_date:
            break
    else:
        days = order.finishing_days_min
        finishing_end = calendar.add_business_days(finishing_start, days)

    # Distribute parts over the finishing window
    total_parts = order.parts_total
    parts_remaining = total_parts
    current_day = finishing_start
    daily_parts = total_parts // days
    extra = total_parts % days

    for i in range(days):
        if not calendar.is_business_day(current_day):
            current_day = calendar.add_business_days(current_day, 1)
        part_count = daily_parts + (1 if i < extra else 0)
        schedule["finishing"].append((current_day, part_count))
        current_day = calendar.add_business_days(current_day, 1)

    return True, schedule


from collections import defaultdict

def firm_schedule(order, start_date, calendar, resources, plan):
    """
    Commit a feasible schedule for an order starting on `start_date` using the provided plan.
    Reserves resources and returns the schedule dictionary + end date.
    """
    schedule = defaultdict(list)
    tons_per_mold = order.parts_per_mold * order.part_weight_ton

    # Reserve resources according to the received plan
    for phase, items in plan.items():
        if phase == "molding":
            for entry in items:
                mold_day = entry["mold_day"]
                qty = entry["qty"]
                flask_release_day = entry["flask_release_day"]
                
                resources.reserve_molds(mold_day, qty)
                resources.reserve_same_part(mold_day, order.order_id, qty)
                resources.reserve_flask(mold_day, flask_release_day, order.flask_size, qty)
                resources.reserve_mix(mold_day, order.product_family, qty)

                schedule[phase].append((mold_day, qty))
        elif phase != "molding":
             for entry in items:
                day, qty = entry
                if phase == "staging":
                    resources.reserve_staging(day, qty)
                elif phase == "pouring":
                    resources.reserve_pouring(day, qty)
                
                schedule[phase].append(entry)

    # Calculate end_date using the last finishing date
    end_date = schedule["finishing"][-1][0]
    

    return schedule, end_date


