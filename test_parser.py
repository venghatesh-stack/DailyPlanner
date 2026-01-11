import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Import the functions under test
from app import (
    extract_date,
    parse_planner_input,
    parse_time_token,
    safe_date,
)

IST = ZoneInfo("Asia/Kolkata")


# -------------------------------------------------
# extract_date tests
# -------------------------------------------------

def test_extract_date_defaults_to_ui_date():
    d = date(2026, 1, 11)
    assert extract_date("Meeting @9am", d) == d


def test_extract_date_explicit_month_text():
    d = date(2026, 1, 11)
    assert extract_date("Task @9am on 15Feb", d) == date(2026, 2, 15)


def test_extract_date_explicit_numeric():
    d = date(2026, 1, 11)
    assert extract_date("Task @9am on 15/02", d) == date(2026, 2, 15)


def test_extract_date_invalid_day_clamped():
    d = date(2026, 2, 10)
    assert extract_date("Task @9am on 31Feb", d) == date(2026, 2, 28)


def test_extract_date_tomorrow():
    d = date(2026, 1, 11)
    assert extract_date("Workout @6am tomorrow", d) == date(2026, 1, 12)


def test_extract_date_next_weekday():
    # Jan 11, 2026 is Sunday
    d = date(2026, 1, 11)
    assert extract_date("Meeting @9am next monday", d) == date(2026, 1, 12)


def test_explicit_date_overrides_relative():
    d = date(2026, 1, 11)
    assert extract_date(
        "Task @9am tomorrow on 15Feb", d
    ) == date(2026, 2, 15)


# -------------------------------------------------
# parse_time_token tests
# -------------------------------------------------

def test_parse_time_token_simple_am():
    d = date(2026, 1, 11)
    dt = parse_time_token("9am", d)
    assert dt.hour == 9 and dt.minute == 0


def test_parse_time_token_with_minutes_pm():
    d = date(2026, 1, 11)
    dt = parse_time_token("7:30pm", d)
    assert dt.hour == 19 and dt.minute == 30


def test_parse_time_token_strips_noise():
    d = date(2026, 1, 11)
    dt = parse_time_token("9am,", d)
    assert dt.hour == 9


# -------------------------------------------------
# parse_planner_input tests
# -------------------------------------------------

def test_parse_single_time_defaults_30_minutes():
    d = date(2026, 1, 11)
    parsed = parse_planner_input("Workout @6am", d)

    assert parsed["start"].hour == 6
    assert parsed["end"] == parsed["start"] + timedelta(minutes=30)
    assert parsed["date"] == d


def test_parse_time_range():
    d = date(2026, 1, 11)
    parsed = parse_planner_input("Meeting @9am to 10am", d)

    assert parsed["start"].hour == 9
    assert parsed["end"].hour == 10


def test_parse_with_date_and_quadrant():
    d = date(2026, 1, 11)
    parsed = parse_planner_input(
        "Fix prod bug @10am tomorrow Q1", d
    )

    assert parsed["date"] == date(2026, 1, 12)
    assert parsed["quadrant"] == "do"


def test_parse_priority_category_tags():
    d = date(2026, 1, 11)
    parsed = parse_planner_input(
        "Yoga @6am $High %Health #fitness #morning", d
    )

    assert parsed["priority"] == "High"
    assert parsed["category"] == "Health"
    assert set(parsed["tags"]) == {"fitness", "morning"}


def test_title_cleanup():
    d = date(2026, 1, 11)
    parsed = parse_planner_input(
        "Review Q4 report @9am Q2", d
    )

    assert parsed["title"] == "Review Q4 report"


def test_end_time_before_start_raises():
    d = date(2026, 1, 11)
    with pytest.raises(ValueError):
        parse_planner_input("Meeting @10am to 9am", d)


def test_missing_time_raises():
    d = date(2026, 1, 11)
    with pytest.raises(ValueError):
        parse_planner_input("Buy groceries tomorrow", d)
