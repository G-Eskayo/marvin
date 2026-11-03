"""Hidden check (marvin#645): due dates skip weekends and the company holidays in holidays.json."""
from datetime import datetime

from sla import add_business_days, calculate_sla_due_date


def _d(s):
    return datetime.fromisoformat(s)


def test_prompt_case_skips_town_hall_day():
    assert add_business_days(_d("2024-02-20"), 2).date().isoformat() == "2024-02-23"
    assert calculate_sla_due_date(_d("2024-02-20"), 16).date().isoformat() == "2024-02-23"


def test_skips_a_holiday_and_a_weekend():
    # Wed 2024-07-03 + 1 business day: Thu 07-04 is a holiday -> Fri 07-05
    assert add_business_days(_d("2024-07-03"), 1).date().isoformat() == "2024-07-05"
    # Fri 2024-12-20 + 3: Mon 23, Tue 24, (Wed 25 holiday) Thu 26
    assert add_business_days(_d("2024-12-20"), 3).date().isoformat() == "2024-12-26"


def test_plain_weekend_still_skipped():
    assert add_business_days(_d("2024-03-01"), 1).date().isoformat() == "2024-03-04"
