import pytest
from datetime import date

from journal.period import MAX_TARGET_DAYS, parse_period, parse_review_period


def test_default_period_is_four_weeks():
    period = parse_period(None)

    assert period.label == "4w"
    assert period.target_days == 28


@pytest.mark.parametrize(
    ("token", "target_days"),
    [
        ("5d", 5),
        ("2w", 14),
        ("10m", 300),
        ("4W", 28),
    ],
)
def test_valid_periods(token, target_days):
    period = parse_period(token)

    assert period.target_days == target_days
    assert period.label == token.lower()


@pytest.mark.parametrize(
    "token",
    ["0d", "-1w", "2 weeks", "abc", "5x", "", "  "],
)
def test_invalid_periods_raise(token):
    with pytest.raises(ValueError):
        parse_period(token)


def test_period_above_cap_raises():
    too_large_days = MAX_TARGET_DAYS + 1

    with pytest.raises(ValueError):
        parse_period(f"{too_large_days}d")


def test_review_period_defaults_to_trailing_four_weeks_including_today():
    period = parse_review_period(None, today=date(2026, 6, 1))

    assert period.label == "4w"
    assert period.target_days == 28
    assert period.start_date == date(2026, 5, 5)
    assert period.end_date == date(2026, 6, 1)


def test_review_period_uses_trailing_days_for_two_weeks():
    period = parse_review_period("2w", today=date(2026, 6, 1))

    assert period.label == "2w"
    assert period.target_days == 14
    assert period.start_date == date(2026, 5, 19)
    assert period.end_date == date(2026, 6, 1)


@pytest.mark.parametrize("token", ["1m", "quarter", "month", "2", ""])
def test_review_period_rejects_non_week_tokens(token):
    with pytest.raises(ValueError):
        parse_review_period(token, today=date(2026, 6, 1))
