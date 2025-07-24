from datetime import date, timedelta
from orders_parser import Strategy
from orders_parser import Order
from orders_parser import OrderStatus
from collections import defaultdict
from math import ceil

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
    
    Parameters:
        order (Order): the order to schedule
        calendar (CalendarManager): date utility
        resources (ResourceManager): shared resource tracker
        try_schedule (function): dry-run feasibility checker
        firm_schedule (function): resource commitment and schedule emitter
        max_search_days (int): how many days forward/backward to explore
        safety_days (int): used only in JIT
        start_date (date or None): if set, override computed start date
        
    Returns:
        dict: {
            "order_id": str,
            "status": OrderStatus,
            "start_date": date or None,
            "end_date": date or None,
            "schedule": dict
        }
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

        if try_schedule(order, start_date, calendar, resources):
            schedule, end_date = firm_schedule(order, start_date, calendar, resources)
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
        return plan_order(order, calendar, resources, try_schedule, firm_schedule,
                          max_search_days=max_search_days, safety_days=0)

    return {
        "order_id": order_id,
        "status": OrderStatus.UNSCHEDULED,
        "start_date": None,
        "end_date": None,
        "schedule": {}
    }

def try_schedule(order, start_date, calendar, resources):
    """
    Simulates full production scheduling of an order starting at `start_date`.
    Returns True if all constraints (including flask/pouring/staging) are met.
    """
    molds_remaining = order.total_molds
    mold_day = start_date
    daily_plan = []

    while molds_remaining > 0:
        if not calendar.is_business_day(mold_day):
            mold_day = calendar.add_business_days(mold_day, 1)
            continue

        # Determine dependent days
        staging_day = calendar.add_calendar_days(mold_day, 1)
        pouring_day = calendar.next_business_day(staging_day)
        cooling_ends = calendar.add_calendar_days(pouring_day, order.cooling_days)
        shakeout_day = calendar.next_business_day(cooling_ends)
        flask_release_day = calendar.next_business_day(shakeout_day)

        # Compute how many molds can be made this day based on mold/pouring/part limits
        max_molds_today = resources.compute_available_molds(order, mold_day, pouring_day)
        max_molds_pouring = resources.compute_available_pouring(order, pouring_day)
        max_molds_flasks = resources.compute_available_flasks(order, flask_release_day, flask_release_day)
        available_today = min(max_molds_today, max_molds_pouring, max_molds_flasks, molds_remaining)

        if available_today <= 0:
            mold_day = calendar.add_business_days(mold_day, 1)
            continue

        # All constraints passed, tentatively accept
        daily_plan.append((mold_day, available_today))
        molds_remaining -= available_today
        mold_day = calendar.add_business_days(mold_day, 1)

    if molds_remaining > 0:
        return False

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
            return True

    # Even minimum duration is late → still feasible, just delayed
    return True


from collections import defaultdict

def firm_schedule(order, start_date, calendar, resources):
    """
    Commit a feasible schedule for an order starting on `start_date`.
    Reserves resources and returns a full schedule dictionary + end date.
    """
    schedule = defaultdict(list)
    molds_remaining = order.total_molds
    mold_day = start_date
    tons_per_mold = order.parts_per_mold * order.part_weight_ton

    while molds_remaining > 0:
        if not calendar.is_business_day(mold_day):
            mold_day = calendar.add_business_days(mold_day, 1)
            continue

        # Calculate dependent steps
        staging_day = calendar.add_calendar_days(mold_day, 1)
        pouring_day = calendar.next_business_day(staging_day)
        cooling_ends = calendar.add_calendar_days(pouring_day, order.cooling_days)
        shakeout_day = calendar.next_business_day(cooling_ends)
        flask_release_day = calendar.next_business_day(shakeout_day)

        # Compute how many molds can be made this day based on mold/pouring/part limits
        max_molds_today = resources.compute_available_molds(order, mold_day, pouring_day)
        max_molds_pouring = resources.compute_available_pouring(order, pouring_day)
        max_molds_flasks = resources.compute_available_flasks(order, flask_release_day, flask_release_day)
        available_today = min(max_molds_today, max_molds_pouring, max_molds_flasks, molds_remaining)

        if available_today <= 0:
            mold_day = calendar.add_business_days(mold_day, 1)
            continue

        # Reserve all resources
        resources.reserve_molds(mold_day, available_today)
        resources.reserve_same_part(mold_day, order.order_id, available_today)
        resources.reserve_flask(mold_day, flask_release_day, order.flask_size, available_today)
        resources.reserve_staging(staging_day, available_today)
        resources.reserve_pouring(pouring_day, available_today * tons_per_mold)

        # Append to schedule
        schedule["molding"].append((mold_day, available_today))
        schedule["staging"].append((staging_day, available_today))
        schedule["pouring"].append((pouring_day, round(available_today * tons_per_mold, 3)))
        schedule["shakeout"].append((shakeout_day, available_today))

        molds_remaining -= available_today
        mold_day = calendar.add_business_days(mold_day, 1)

    # Final stages after shakeout
    last_mold_day = schedule["molding"][-1][0]
    staging_day = calendar.add_calendar_days(last_mold_day, 1)
    pouring_day = calendar.next_business_day(staging_day)
    cooling_ends = calendar.add_calendar_days(pouring_day, order.cooling_days)
    shakeout_day = calendar.next_business_day(cooling_ends)
    finishing_start = calendar.next_business_day(shakeout_day)

    # Determine finishing window (favor nominal if possible)
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

    return schedule, finishing_end


