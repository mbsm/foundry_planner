from collections import defaultdict
from datetime import date, timedelta
import yaml

from orders_parser import FlaskSize  # adjust import to match your module layout

def load_resource_config(path):
    with open(path, 'r') as f:
        cfg = yaml.safe_load(f)

    flask_enum = {v.value: v for v in FlaskSize}
    flask_limits = {flask_enum[k]: v for k, v in cfg["flask_limits"].items()}

    return ResourceManager(
        flask_limits=flask_limits,
        mold_limit_per_day=cfg["max_molds_per_day"],
        pouring_limit_per_day=cfg["max_pouring_tons_per_day"],
        pattern_limit_per_day=cfg["max_patterns_per_day"],
        staging_limit=cfg["max_staging_molds"],
        max_same_part_molds=cfg["max_same_part_molds_per_day"]
    )

class ResourceManager:
    def __init__(self, flask_limits, mold_limit_per_day, pouring_limit_per_day, pattern_limit_per_day, staging_limit, max_same_part_molds):
        self.flask_limits = flask_limits
        self.max_molds_per_day = mold_limit_per_day
        self.max_pouring_tons_per_day = pouring_limit_per_day
        self.max_patterns_per_day = pattern_limit_per_day
        self.max_staging_molds = staging_limit
        self.max_same_part_molds_per_day = max_same_part_molds

        self.flask_pool = defaultdict(lambda: defaultdict(int))
        self.daily_molds = defaultdict(int)
        self.daily_pouring = defaultdict(float)
        self.pattern_slots = defaultdict(int)
        self.staging_area = defaultdict(int)
        self.same_part_molds = defaultdict(lambda: defaultdict(int))

    
    def can_allocate_flask(self, start_day, end_day, flask_size, quantity):
        current = start_day
        while current <= end_day:
            used = self.flask_pool[current][flask_size]
            limit = self.flask_limits.get(flask_size, 0)
            if used + quantity > limit:
                return False
            current += timedelta(days=1)
        return True

    def reserve_flask(self, start_day, end_day, flask_size, quantity):
        current = start_day
        while current <= end_day:
            self.flask_pool[current][flask_size] += quantity
            current += timedelta(days=1)

    def can_schedule_molds(self, day, quantity):
        return self.daily_molds[day] + quantity <= self.max_molds_per_day

    def reserve_molds(self, day, quantity):
        self.daily_molds[day] += quantity

    def can_schedule_pouring(self, day, tons):
        return self.daily_pouring[day] + tons <= self.max_pouring_tons_per_day

    def reserve_pouring(self, day, tons):
        self.daily_pouring[day] += tons

    def can_schedule_pattern(self, day):
        return self.pattern_slots[day] < self.max_patterns_per_day

    def reserve_pattern(self, day):
        self.pattern_slots[day] += 1

    def can_stage_molds(self, day, quantity):
        return self.staging_area[day] + quantity <= self.max_staging_molds

    def reserve_staging(self, day, quantity):
        self.staging_area[day] += quantity

    def can_schedule_same_part(self, day, part_number, quantity):
        return self.same_part_molds[day][part_number] + quantity <= self.max_same_part_molds_per_day

    def reserve_same_part(self, day, part_number, quantity):
        self.same_part_molds[day][part_number] += quantity

    def compute_available_molds(self, order, mold_day, pouring_day, molds_remaining):
        """Compute the number of molds that can be scheduled on `mold_day` based on pouring, mold, and per-part constraints."""
        tons_per_mold = order.parts_per_mold * order.part_weight_ton
        pouring_capacity_left = self.max_pouring_tons_per_day - self.daily_pouring[pouring_day]
        max_by_pouring = int(pouring_capacity_left // tons_per_mold)
        total_molds_available = self.max_molds_per_day - self.daily_molds[mold_day]
        max_same_part_molds = self.max_same_part_molds_per_day - self.same_part_molds[mold_day][order.order_id]
        max_flasks_available = self.flask_limits[order.flask_size] - self.flask_pool[mold_day][order.flask_size]

        return min(total_molds_available, max_same_part_molds, max_by_pouring, max_flasks_available, molds_remaining)

