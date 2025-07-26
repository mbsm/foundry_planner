from collections import defaultdict
from datetime import date, timedelta
from math import floor
import json
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
        max_same_part_molds=cfg["max_same_part_molds_per_day"],
        product_family_max_mix=cfg["product_family_max_mix"]
    )

class ResourceManager:
    def __init__(self, flask_limits, 
                 mold_limit_per_day, 
                 pouring_limit_per_day, 
                 pattern_limit_per_day, 
                 staging_limit, 
                 max_same_part_molds, 
                 product_family_max_mix):
        self.flask_limits = flask_limits
        self.max_molds_per_day = mold_limit_per_day
        self.max_pouring_tons_per_day = pouring_limit_per_day
        self.max_patterns_per_day = pattern_limit_per_day
        self.max_staging_molds = staging_limit
        self.max_same_part_molds_per_day = max_same_part_molds
        # convert the {'familia': max_mix_str} to {familia: max_mix_float}
        self.product_family_max_mix = {k: float(v.strip().strip('%'))/100 for k, v in product_family_max_mix.items()}

        # Initialize resource usage tracking
        self.flask_pool = defaultdict(lambda: defaultdict(int)) # daily usage per flask size
        self.daily_molds = defaultdict(int) # daily molds scheduled
        self.daily_pouring = defaultdict(float) # daily pouring tons scheduled
        self.pattern_slots = defaultdict(int) # daily pattern slots used
        self.staging_area = defaultdict(int) # daily staging area usage
        self.same_part_molds = defaultdict(lambda: defaultdict(int)) # daily same part molds usage
        self.product_family_usage = defaultdict(lambda: defaultdict(int))  # usage[day][family]
    
    '''def can_allocate_flask(self, start_day, end_day, flask_size, quantity):
        current = start_day
        while current <= end_day:
            used = self.flask_pool[current][flask_size]
            limit = self.flask_limits.get(flask_size, 0)
            if used + quantity > limit:
                return False
            current += timedelta(days=1)
        return True'''

    def reserve_flask(self, start_day, end_day, flask_size, quantity):
        current = start_day
        while current <= end_day:
            self.flask_pool[current][flask_size] += quantity
            current += timedelta(days=1)

    '''def can_schedule_molds(self, day, quantity):
        return self.daily_molds[day] + quantity <= self.max_molds_per_day'''

    def reserve_molds(self, day, quantity):
        self.daily_molds[day] += quantity

    '''def can_schedule_pouring(self, day, tons):
        return self.daily_pouring[day] + tons <= self.max_pouring_tons_per_day'''

    def reserve_pouring(self, day, tons):
        self.daily_pouring[day] += tons

    def can_schedule_pattern(self, day):
        return self.pattern_slots[day] < self.max_patterns_per_day

    def reserve_pattern(self, day):
        self.pattern_slots[day] += 1

    '''def can_stage_molds(self, day, quantity):
        return self.staging_area[day] + quantity <= self.max_staging_molds'''

    def reserve_staging(self, day, quantity):
        self.staging_area[day] += quantity

    '''def can_schedule_same_part(self, day, part_number, quantity):
        return self.same_part_molds[day][part_number] + quantity <= self.max_same_part_molds_per_day'''

    def reserve_same_part(self, day, part_number, quantity):
        self.same_part_molds[day][part_number] += quantity

    def compute_available_molds(self, order, mold_day, pouring_day):
        """Compute the number of molds that can be scheduled on `mold_day` mold, and per-part constraints."""
        total_molds_available = self.max_molds_per_day - self.daily_molds[mold_day]
        max_same_part_molds = self.max_same_part_molds_per_day - self.same_part_molds[mold_day][order.order_id]
        return min(total_molds_available, max_same_part_molds)

    def compute_available_pouring(self, order, pouring_day):
        """Compute the available pouring capacity in molds for a given order on `pouring_day`."""
        tons_per_mold = order.parts_per_mold * order.part_weight_ton
        pouring_capacity_left = self.max_pouring_tons_per_day - self.daily_pouring[pouring_day]
        return floor(pouring_capacity_left /tons_per_mold)
    
    def compute_available_flasks(self, order, start_day, end_day):
        """Compute the available flasks for an order over a range of days
           the available flasks are the minimum of the daily limits for the rage
        """
        min_flasks = float('inf')
        current = start_day
        while current <= end_day:
            limit = self.flask_limits.get(order.flask_size, 0)
            min_flasks = min(min_flasks, limit - self.flask_pool[current][order.flask_size])
            current += timedelta(days=1)

        return max(0, min_flasks)

    def compute_available_mix(self, order, day):
        """Compute the available mix for an order on a given day."""
        if order.product_family not in self.product_family_max_mix:
            return float('inf')
        # Accede al uso de mezcla en ese día y familia
        used = self.product_family_usage[day][order.product_family]
        return floor(self.product_family_max_mix[order.product_family] * self.max_molds_per_day - used)

    def reserve_mix(self, day, family, quantity):
        if family in self.product_family_max_mix:
            self.product_family_usage[day][family] += quantity

    def save_state_json(self, filepath):
        """Guarda el estado actual del ResourceManager en disco en formato JSON."""
        def serialize_defaultdict(d):
            return {str(k): dict(v) if isinstance(v, defaultdict) else v for k, v in d.items()}

        state = {
            "flask_pool": {str(k): dict(v) for k, v in self.flask_pool.items()},
            "daily_molds": {str(k): v for k, v in self.daily_molds.items()},
            "daily_pouring": {str(k): v for k, v in self.daily_pouring.items()},
            "pattern_slots": {str(k): v for k, v in self.pattern_slots.items()},
            "staging_area": {str(k): v for k, v in self.staging_area.items()},
            "same_part_molds": {str(k): dict(v) for k, v in self.same_part_molds.items()},
        }
        with open(filepath, "w") as f:
            json.dump(state, f, indent=2)

    def load_state_json(self, filepath):
        """Carga el estado guardado en disco en formato JSON al ResourceManager."""
        with open(filepath, "r") as f:
            state = json.load(f)
        # flask_pool
        self.flask_pool = defaultdict(lambda: defaultdict(int))
        for k, v in state["flask_pool"].items():
            day = date.fromisoformat(k)
            for flask, val in v.items():
                self.flask_pool[day][flask] = val
        # daily_molds
        self.daily_molds = defaultdict(int)
        for k, v in state["daily_molds"].items():
            day = date.fromisoformat(k)
            self.daily_molds[day] = v
        # daily_pouring
        self.daily_pouring = defaultdict(float)
        for k, v in state["daily_pouring"].items():
            day = date.fromisoformat(k)
            self.daily_pouring[day] = v
        # pattern_slots
        self.pattern_slots = defaultdict(int)
        for k, v in state["pattern_slots"].items():
            day = date.fromisoformat(k)
            self.pattern_slots[day] = v
        # staging_area
        self.staging_area = defaultdict(int)
        for k, v in state["staging_area"].items():
            day = date.fromisoformat(k)
            self.staging_area[day] = v
        # same_part_molds
        self.same_part_molds = defaultdict(lambda: defaultdict(int))
        for k, v in state["same_part_molds"].items():
            day = date.fromisoformat(k)
            for part, val in v.items():
                self.same_part_molds[day][part] = val
