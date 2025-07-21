from collections import defaultdict
from datetime import date

class ResourceManager:
    def __init__(self, flask_limits, mold_limit_per_day, pouring_limit_per_day, pattern_limit_per_day, staging_limit):
        # Capacity settings
        self.flask_limits = flask_limits  # {FlaskSize.F105: 10, FlaskSize.F120: 8, ...}
        self.max_molds_per_day = mold_limit_per_day
        self.max_pouring_tons_per_day = pouring_limit_per_day
        self.max_patterns_per_day = pattern_limit_per_day
        self.max_staging_molds = staging_limit

        # Resource usage state
        self.flask_pool = defaultdict(lambda: defaultdict(int))  # flask_pool[date][FlaskSize] = count used
        self.daily_molds = defaultdict(int)                      # daily_molds[date] = molds used
        self.daily_pouring = defaultdict(float)                  # daily_pouring[date] = tons poured
        self.pattern_slots = defaultdict(int)                    # pattern_slots[date] = patterns scheduled
        self.staging_area = defaultdict(int)                     # staging_area[date] = molds staged

    def can_allocate_flask(self, day, flask_size, quantity):
        used = self.flask_pool[day][flask_size]
        return used + quantity <= self.flask_limits.get(flask_size, 0)

    def reserve_flask(self, day, flask_size, quantity):
        self.flask_pool[day][flask_size] += quantity

    def release_flask(self, day, flask_size, quantity):
        self.flask_pool[day][flask_size] = max(0, self.flask_pool[day][flask_size] - quantity)

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
