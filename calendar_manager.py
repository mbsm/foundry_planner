from datetime import datetime, timedelta
import yaml

class CalendarManager:
    def __init__(self, holidays_file):
        self.holidays = self._load_holidays(holidays_file)

    def _load_holidays(self, file_path):
        with open(file_path, "r") as f:
            holidays_raw = yaml.safe_load(f)
        
        holidays = set()
        for entry in holidays_raw:
            if isinstance(entry, str):
                holidays.add(datetime.strptime(entry.strip(), "%Y-%m-%d").date())
        return holidays

    def is_business_day(self, date):
        return date.weekday() < 5 and date not in self.holidays

    def next_business_day(self, date):
        next_day = date + timedelta(days=1)
        while not self.is_business_day(next_day):
            next_day += timedelta(days=1)
        return next_day

    def prev_business_day(self, date):
        prev_day = date - timedelta(days=1)
        while not self.is_business_day(prev_day):
            prev_day -= timedelta(days=1)
        return prev_day

    def add_business_days(self, start_date, n):
        delta = timedelta(days=1 if n >= 0 else -1)
        current_date = start_date
        count = 0
        while count < abs(n):
            current_date += delta
            if self.is_business_day(current_date):
                count += 1
        return current_date

    def add_calendar_days(self, start_date, n):
        return start_date + timedelta(days=n)

# Example usage:
if __name__ == "__main__":
    cal = CalendarManager("holidays.yaml")
    today = datetime.today().date()
    print("Today:", today)
    print("Is business day:", cal.is_business_day(today))
    print("Next business day:", cal.next_business_day(today))
    print("Previous business day:", cal.prev_business_day(today))
    print("7 business days later:", cal.add_business_days(today, 7))
    print("7 calendar days later:", cal.add_calendar_days(today, 7))