from math import ceil
from enum import Enum
from datetime import datetime, date
import yaml

class OrderState(Enum):
    PENDING = 0
    IN_PROGRESS = 1
    COMPLETED = 2

class OrderStatus(Enum):
    UNSCHEDULED = 0
    ONTIME = 1
    DELAYED = 2

class FlaskSize(Enum):
    F105 = "F105"
    F120 = "F120"
    F143 = "F143"

class Strategy(Enum):
    ASAP = "ASAP"
    JIT = "JIT"

class OrderType(Enum):
    NEW = "new"
    REPETITION = "recurrent"

class Alloy(Enum):
    CM1 = "CM1"
    CM2 = "CM2"
    CM3 = "CM3"
    CM4 = "CM4"
    SP1 = "SP1"
    SPX = "SPX"
    CMHC = "CMHC"
    CMZG = "CMZG"
    WS120 = "WS120"
    WS140 = "WS140"
    WS170 = "WS170"
    WS302 = "WS302"
    WS304 = "WS304"
    WS306 = "WS306"

class Order:
    def __init__(self, order_id):
        self.order_id = order_id
        self.strategy = None
        self.is_new = None
        self.due_date = None
        self.pattern_days = 0
        self.sample_molds = 0
        self.cooling_days = 0
        self.finishing_days_nominal = 15
        self.finishing_days_min = 10
        self.parts_total = 0
        self.parts_per_mold = 1
        self.part_weight_ton = 0.0
        self.flask_size = None
        self.state = OrderState.PENDING
        self.status = OrderStatus.UNSCHEDULED
        self.alloy = None
        self.total_molds = 0
        self.produced_molds = 0
        self.scraped_molds = 0
        self.product_family = ''

    def compute_estimated_duration(self, max_molds_per_day):
        total_molds = ceil(self.parts_total / self.parts_per_mold)
        remaining_molds = total_molds - self.produced_molds - self.scraped_molds
        molding_days = ceil(remaining_molds / max_molds_per_day)
        molding_days += (molding_days // 5) * 2  # approx weekend overhead
        return molding_days + self.cooling_days + self.finishing_days_nominal

def parse_orders(file_path):
    with open(file_path, "r") as f:
        raw_orders = yaml.safe_load(f)

    orders = []

    for raw in raw_orders:
        order = Order(order_id=raw["order_id"])
        order.parts_total = raw["quantity"]
        order.parts_per_mold = raw["parts_per_mold"]
        order.part_weight_ton = raw["part_weight"]
        order.part_number = raw["part_number"]
        order.order_type = OrderType(raw["order_type"])
        order.flask_size = FlaskSize(raw["flask_size"])
        order.product_family = raw["product_family"]

        # Safe due_date parsing
        due_raw = raw["due_date"]
        if isinstance(due_raw, str):
            order.due_date = datetime.strptime(due_raw, "%Y-%m-%d").date()
        elif isinstance(due_raw, date):
            order.due_date = due_raw
        else:
            raise ValueError(f"Invalid due date format: {due_raw}")

        order.is_new = raw["order_type"] == "new"
        order.cooling_days = raw["cooling_days"]
        order.strategy = Strategy(raw["strategy"])
        order.finishing_days_nominal = raw["finishing_time"]["nominal"]
        order.finishing_days_min = raw["finishing_time"]["minimum"]
        order.produced_molds = raw.get("produced_molds", 0)
        order.scraped_molds = raw.get("scraped_molds", 0)
        order.alloy = raw["alloy"]
        order.total_molds = ceil(order.parts_total / order.parts_per_mold)

        if order.is_new:
            order.pattern_days = raw.get("pattern_time", 0)
            order.sample_molds = raw.get("molds_to_sample", 0)

        orders.append(order)

    return orders


# Example usage:

def main():
    orders = parse_orders("orders.yaml")
    max_molds_per_day = 5  # Example value, adjust as needed
    for order in orders:
        print(f"Order ID: {order.order_id}, Due Date: {order.due_date}, Total Molds: {order.total_molds}")
        print(f"  Estimated Production Days (Max {max_molds_per_day} molds/day): {order.compute_estimated_duration(max_molds_per_day)}")

if __name__ == "__main__":
   main()