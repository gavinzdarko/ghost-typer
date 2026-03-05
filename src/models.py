"""Data models for Ghost Typer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class FormatType(Enum):
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    HEADING_4 = "heading_4"
    HEADING_5 = "heading_5"
    HEADING_6 = "heading_6"
    NUMBERED_LIST = "numbered_list"
    BULLETED_LIST = "bulleted_list"
    ALIGN_LEFT = "align_left"
    ALIGN_CENTER = "align_center"
    ALIGN_RIGHT = "align_right"
    ALIGN_JUSTIFY = "align_justify"


@dataclass
class TextSegment:
    """A segment of text with associated formatting."""

    text: str
    formatting: dict[str, Any] = field(default_factory=dict)

    @property
    def bold(self) -> bool:
        return self.formatting.get("bold", False)

    @property
    def italic(self) -> bool:
        return self.formatting.get("italic", False)

    @property
    def underline(self) -> bool:
        return self.formatting.get("underline", False)

    @property
    def heading_level(self) -> int:
        return self.formatting.get("heading_level", 0)

    @property
    def list_type(self) -> str | None:
        return self.formatting.get("list_type", None)

    @property
    def alignment(self) -> str | None:
        return self.formatting.get("alignment", None)


# --- TypingAction hierarchy ---


@dataclass
class TypingAction:
    """Base class for all typing actions."""

    description: str = ""


@dataclass
class TypeText(TypingAction):
    """Type a string of text character by character with realistic timing."""

    text: str = ""

    def __post_init__(self):
        if not self.description:
            preview = self.text[:40] + ("..." if len(self.text) > 40 else "")
            self.description = f"Type: {preview!r}"


@dataclass
class ApplyFormatting(TypingAction):
    """Apply formatting via a keyboard shortcut."""

    format_type: FormatType = FormatType.BOLD
    shortcut: tuple[str, ...] = ("cmd", "b")

    def __post_init__(self):
        if not self.description:
            self.description = f"Format: {self.format_type.value} ({'+'.join(self.shortcut)})"


@dataclass
class Pause(TypingAction):
    """Pause for a duration (simulating thinking, reading, etc.)."""

    duration: float = 1.0

    def __post_init__(self):
        if not self.description:
            self.description = f"Pause: {self.duration:.1f}s"


@dataclass
class MakeMistake(TypingAction):
    """Type wrong text, then backspace and type the correct text."""

    wrong_text: str = ""
    correct_text: str = ""
    chars_before_noticing: int = 0

    def __post_init__(self):
        if not self.description:
            self.description = (
                f"Mistake: {self.wrong_text!r} -> {self.correct_text!r} "
                f"(notice after {self.chars_before_noticing} extra chars)"
            )


@dataclass
class Rewrite(TypingAction):
    """Delete back some characters and retype with new text."""

    delete_count: int = 0
    new_text: str = ""

    def __post_init__(self):
        if not self.description:
            self.description = f"Rewrite: delete {self.delete_count} chars, type {self.new_text!r}"


@dataclass
class PressKey(TypingAction):
    """Press a special key (enter, tab, etc.)."""

    key: str = "enter"

    def __post_init__(self):
        if not self.description:
            self.description = f"Press: {self.key}"


# --- TypingPlan ---


@dataclass
class TypingPlan:
    """A complete plan of typing actions to execute."""

    actions: list[TypingAction] = field(default_factory=list)
    total_characters: int = 0
    estimated_duration_seconds: float = 0.0
    segment_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, action: TypingAction) -> None:
        self.actions.append(action)

    def __len__(self) -> int:
        return len(self.actions)

    def __iter__(self):
        return iter(self.actions)


# --- Settings ---


@dataclass
class Settings:
    """All configurable settings for Ghost Typer."""

    # Speed — research: teens average 40-50 WPM on desktop
    wpm: int = 57
    wpm_variance: int = 12

    # Errors — teen peeker: high raw error rate, notices late
    error_rate: float = 0.035
    # 40% immediate, 60% delayed (peeker looking at keyboard, not screen)
    correction_delay_chars_min: int = 0
    correction_delay_chars_max: int = 6

    # Pauses — research: cognitive pauses at 2s+ threshold
    pause_frequency: float = 0.15
    pause_duration_min: float = 0.3
    pause_duration_max: float = 4.0

    # Fatigue — research: +4% slower over 2hr, errors +19%
    fatigue_enabled: bool = True
    fatigue_rate: float = 0.0015

    # Burst typing — research: bursts of 1-3 words (~5-15 chars)
    burst_typing_enabled: bool = True
    burst_length_min: int = 5
    burst_length_max: int = 15
    burst_speed_multiplier: float = 1.25

    # Rewriting — teen types rough version first, then deletes and retypes correctly
    rewrite_probability: float = 0.07
    rewrite_max_words: int = 12

    # Human errors (grammar/punctuation — teen-style, left uncorrected)
    grammar_error_rate: float = 0.15
    punctuation_error_rate: float = 0.20

    # False alarm rate — very rare, teen occasionally second-guesses a correct word
    false_alarm_rate: float = 0.008

    # Sentence / paragraph pauses — research: sentences 1.5-4s, paragraphs 3-10s
    sentence_pause_min: float = 0.8
    sentence_pause_max: float = 2.5
    paragraph_pause_min: float = 2.5
    paragraph_pause_max: float = 7.0

    @property
    def correction_delay_chars(self) -> tuple[int, int]:
        return (self.correction_delay_chars_min, self.correction_delay_chars_max)

    @correction_delay_chars.setter
    def correction_delay_chars(self, value: tuple[int, int]) -> None:
        self.correction_delay_chars_min, self.correction_delay_chars_max = value

    @property
    def pause_duration_range(self) -> tuple[float, float]:
        return (self.pause_duration_min, self.pause_duration_max)

    @pause_duration_range.setter
    def pause_duration_range(self, value: tuple[float, float]) -> None:
        self.pause_duration_min, self.pause_duration_max = value

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> Settings:
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
