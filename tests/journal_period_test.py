import pytest

from journal.period import MAX_TARGET_DAYS, parse_period


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
