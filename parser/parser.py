from dataclasses import dataclass, field
from typing import List, Literal, Optional
import re


# =========================
# Models
# =========================

@dataclass
class DailyCheckIn:
    energy: int
    focus: int
    satisfaction: int

    did_today: List[str] = field(default_factory=list)
    meaningful: List[str] = field(default_factory=list)
    drained: List[str] = field(default_factory=list)
    tomorrow_focus: List[str] = field(default_factory=list)


@dataclass
class WeeklyReview:
    momentum: List[str] = field(default_factory=list)
    friction: List[str] = field(default_factory=list)
    avoidance: List[str] = field(default_factory=list)
    meaningful: List[str] = field(default_factory=list)
    fake_productivity: List[str] = field(default_factory=list)
    next_week_focus: List[str] = field(default_factory=list)


# =========================
# Parser
# =========================

class CheckupParser:
    @staticmethod
    def detect_type(markdown: str) -> Literal["daily", "weekly", "unknown"]:
        if re.search(r"^\s*##\s+Daily Check-In\s*$", markdown, re.MULTILINE):
            return "daily"

        if re.search(r"^\s*##\s+.+\bReview\b\s*$", markdown, re.MULTILINE):
            return "weekly"

        return "unknown"

    @staticmethod
    def parse(markdown: str):
        detected = CheckupParser.detect_type(markdown)

        if detected == "daily":
            return CheckupParser._parse_daily(markdown)

        if detected == "weekly":
            return CheckupParser._parse_weekly(markdown)

        raise ValueError("Unknown check-in format")

    @staticmethod
    def _parse_daily(md: str) -> DailyCheckIn:
        return DailyCheckIn(
            energy=CheckupParser._extract_score(md, "Energy"),
            focus=CheckupParser._extract_score(md, "Focus"),
            satisfaction=CheckupParser._extract_score(md, "Satisfaction"),

            did_today=CheckupParser._extract_bullets(
                md,
                "What did I actually do today?"
            ),

            meaningful=CheckupParser._extract_bullets(
                md,
                "What felt meaningful?"
            ),

            drained=CheckupParser._extract_bullets(
                md,
                "What drained me?"
            ),

            tomorrow_focus=CheckupParser._extract_bullets(
                md,
                "What should tomorrow focus on?"
            ),
        )

    @staticmethod
    def _parse_weekly(md: str) -> WeeklyReview:
        return WeeklyReview(
            momentum=CheckupParser._extract_bullets(md, "Momentum"),
            friction=CheckupParser._extract_bullets(md, "Friction"),
            avoidance=CheckupParser._extract_bullets(md, "Avoidance"),
            meaningful=CheckupParser._extract_bullets(md, "Meaningful"),
            fake_productivity=CheckupParser._extract_bullets(md, "Fake productivity"),
            next_week_focus=CheckupParser._extract_bullets(md, "Next Week Focus"),
        )

    @staticmethod
    def _extract_score(md: str, label: str) -> int:
        pattern = rf"{re.escape(label)}:\s*(\d+)/10"
        match = re.search(pattern, md)

        if not match:
            raise ValueError(f"Missing score for {label}")

        return int(match.group(1))

    @staticmethod
    def _extract_bullets(md: str, section: str) -> List[str]:
        pattern = (
            rf"{re.escape(section)}:?\s*\n"
            r"((?:- .+\n?)*)"
        )

        match = re.search(pattern, md, re.MULTILINE)

        if not match:
            return []

        raw = match.group(1)

        return [
            line.removeprefix("- ").strip()
            for line in raw.strip().splitlines()
            if line.strip()
        ]


# =========================
# Example Usage
# =========================

daily_md = """
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

weekly_md = """
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
