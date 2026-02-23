from datetime import datetime,date
import calendar

def safe_date(year, month, day):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def safe_date_from_string(date_str):
    if not date_str:
        return date.today()

    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return safe_date(parsed.year, parsed.month, parsed.day)
    except ValueError:
        return date.today()