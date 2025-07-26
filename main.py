from calendar_manager import CalendarManager
from orders_parser import parse_orders, OrderStatus
from resource_manager import load_resource_config
from planner_engine import plan_full_order
from reports import print_weekly_report, print_schedule_summary, print_daily_resource_usage_report

import json
from datetime import date
import logging

# Display logs to console and write to a file
logging.basicConfig(
    level=logging.INFO,  # Or DEBUG for more detail
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        #logging.StreamHandler(),  # Console output
        logging.FileHandler("planner.log", mode='w')  # File output
    ]
)

def main():

    # Load calendar
    calendar = CalendarManager("holidays.yaml")

    # Load resources
    resources = load_resource_config("resources.yaml")

    # Load orders
    orders = parse_orders("orders.yaml")

    # Sort orders by latest safe start (due - est_duration)
    orders.sort(
        key=lambda o: (
            (o.due_date - timedelta(days=o.compute_estimated_duration(resources.max_molds_per_day))) - date.today()
        ).days
    )

    full_plan = {}
    delayed = []
    unscheduled = []

    start_date = date.today()
    end_date = start_date + timedelta(days=14)

    for order in orders:
        plan = plan_full_order(order, calendar, resources)

        full_plan[order.order_id] = {
            "status": plan["status"].name,
            "start_date": plan["start_date"].isoformat() if plan["start_date"] else None,
            "end_date": plan["end_date"].isoformat() if plan["end_date"] else None,
            "schedule": {
                phase: [(d.isoformat(), v) for d, v in phase_data]
                for phase, phase_data in plan["schedule"].items()
            }
        }

        if plan["status"] == OrderStatus.DELAYED:
            delayed.append(order.order_id)
        elif plan["status"] == OrderStatus.UNSCHEDULED:
            unscheduled.append(order.order_id)



    print_schedule_summary(full_plan, orders)
    print_weekly_report(full_plan, orders, resources)

    # save full plan to JSON
    with open("full_plan.json", "w") as f:
        json.dump(full_plan, f, indent=4, default=str)
        logging.info("Full plan saved to full_plan.json")


if __name__ == "__main__":
    from datetime import timedelta
    main()
