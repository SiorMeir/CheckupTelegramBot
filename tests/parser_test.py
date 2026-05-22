import pytest

from parser import (
    CheckupParser,
    DailyCheckIn,
    WeeklyReview,
)


def test_parse_daily_checkin():
    markdown = """
## Daily Check-In

Energy: 7/10
Focus: 5/10
Satisfaction: 8/10

What did I actually do today?
- Finished Telegram webhook
- Fixed SQLite locking issue
- Gym workout

What felt meaningful?
- Solving the retry bug properly
- Seeing the bot deployed on k3s

What drained me?
- 2h YouTube spiral
- Context switching

What should tomorrow focus on?
- Worker queue
"""

    result = CheckupParser.parse(markdown)

    assert isinstance(result, DailyCheckIn)

    assert result.energy == 7
    assert result.focus == 5
    assert result.satisfaction == 8

    assert result.did_today == [
        "Finished Telegram webhook",
        "Fixed SQLite locking issue",
        "Gym workout",
    ]

    assert result.meaningful == [
        "Solving the retry bug properly",
        "Seeing the bot deployed on k3s",
    ]

    assert result.drained == [
        "2h YouTube spiral",
        "Context switching",
    ]

    assert result.tomorrow_focus == [
        "Worker queue",
    ]


def test_parse_weekly_review():
    markdown = """
## Week 2 Review

Momentum:
- Daily coding sessions worked well
- Shipping small vertical slices helped

Friction:
- Spent too much time comparing ingress solutions
- Stayed up too late twice

Avoidance:
- Delayed worker retry logic because it felt “hard”

Meaningful:
- Telegram bot finally felt real
- Deploying to k3s was exciting

Fake productivity:
- Watching Kubernetes videos instead of implementing

Next Week Focus:
- Finish async worker pipeline
- No infra changes unless blocking
"""

    result = CheckupParser.parse(markdown)

    assert isinstance(result, WeeklyReview)

    assert result.momentum == [
        "Daily coding sessions worked well",
        "Shipping small vertical slices helped",
    ]

    assert result.friction == [
        "Spent too much time comparing ingress solutions",
        "Stayed up too late twice",
    ]

    assert result.avoidance == [
        "Delayed worker retry logic because it felt “hard”",
    ]

    assert result.meaningful == [
        "Telegram bot finally felt real",
        "Deploying to k3s was exciting",
    ]

    assert result.fake_productivity == [
        "Watching Kubernetes videos instead of implementing",
    ]

    assert result.next_week_focus == [
        "Finish async worker pipeline",
        "No infra changes unless blocking",
    ]


def test_invalid_format():
    markdown = "# Random Note"

    with pytest.raises(ValueError):
        CheckupParser.parse(markdown)