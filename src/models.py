"""Data models for Ghost Typer."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# TypingProfile — AI-generated behavioral fingerprint (replaces all hardcoded
# constants in typing_engine, typing_planner, and orchestrator).
# ---------------------------------------------------------------------------


@dataclass
class Range:
    """A min/max range for random sampling."""
    min: float = 0.0
    max: float = 1.0

    def clamp(self, floor: float = 0.0, ceil: float = 100.0) -> "Range":
        return Range(
            min=builtins_max(floor, builtins_min(self.min, ceil)),
            max=builtins_max(floor, builtins_min(self.max, ceil)),
        )


@dataclass
class IntRange:
    """A min/max range for integer sampling."""
    min: int = 0
    max: int = 1


@dataclass
class KeystrokeTiming:
    """All per-character delay multiplier ranges."""
    shift_multiplier: Range = field(default_factory=lambda: Range(1.40, 2.00))
    end_punctuation_multiplier: Range = field(default_factory=lambda: Range(1.20, 1.45))
    mid_punctuation_multiplier: Range = field(default_factory=lambda: Range(1.15, 1.40))
    digit_multiplier: Range = field(default_factory=lambda: Range(1.50, 2.20))
    symbol_multiplier: Range = field(default_factory=lambda: Range(1.30, 1.80))
    hunt_key_multiplier: Range = field(default_factory=lambda: Range(1.15, 1.40))
    jitter_sigma: float = 0.30
    warmup_chars: int = 15
    warmup_slowdown: float = 0.20
    first_char_of_word_multiplier: Range = field(default_factory=lambda: Range(1.15, 1.40))
    early_word_multiplier: Range = field(default_factory=lambda: Range(0.95, 1.10))
    mid_word_multiplier: Range = field(default_factory=lambda: Range(0.88, 0.98))
    fast_digraph_multiplier: Range = field(default_factory=lambda: Range(0.88, 0.96))
    slow_digraph_multiplier: Range = field(default_factory=lambda: Range(1.08, 1.25))
    common_word_short_multiplier: Range = field(default_factory=lambda: Range(0.80, 0.90))
    common_word_long_multiplier: Range = field(default_factory=lambda: Range(0.93, 0.99))
    common_double_multiplier: Range = field(default_factory=lambda: Range(0.85, 0.95))
    uncommon_double_multiplier: Range = field(default_factory=lambda: Range(0.95, 1.12))
    space_normal_multiplier: Range = field(default_factory=lambda: Range(1.0, 1.4))
    space_thinking_multiplier: Range = field(default_factory=lambda: Range(1.8, 3.5))
    space_thinking_probability: float = 0.70
    enter_multiplier: Range = field(default_factory=lambda: Range(1.4, 2.0))
    post_error_multiplier: Range = field(default_factory=lambda: Range(1.12, 1.35))
    delay_clamp_min: float = 0.035
    delay_clamp_max: float = 2.000
    # Feature 1: Bimodal IKI — two Gaussian modes (fast automatized vs slow hunt)
    bimodal_fast_probability: float = 0.65  # chance of sampling from fast mode
    bimodal_fast_sigma: float = 0.18        # tight spread for automatized keystrokes
    bimodal_slow_sigma: float = 0.45        # wide spread for hunt-and-peck keystrokes
    bimodal_slow_multiplier: float = 1.35   # slow mode base is slower
    # Feature 5: Finger-specific speed multipliers (index=fast, pinky=slow)
    finger_index_multiplier: float = 0.92
    finger_middle_multiplier: float = 0.96
    finger_ring_multiplier: float = 1.08
    finger_pinky_multiplier: float = 1.18
    finger_thumb_multiplier: float = 1.0    # spacebar
    # Feature 6: Hand alternation (alternating hands is faster)
    hand_alternation_multiplier: float = 0.90   # bonus for switching hands
    same_hand_multiplier: float = 1.06           # penalty for same hand
    same_finger_multiplier: float = 1.20         # worse penalty for same finger
    # Feature 3: Syllable boundary micro-pause
    syllable_pause_multiplier: Range = field(default_factory=lambda: Range(1.05, 1.20))


@dataclass
class KeyKnowledge:
    """Which keys/words are easy or hard for THIS typist on THIS text."""
    hunt_keys: list[str] = field(default_factory=lambda: list("zxqjkv"))
    common_doubles: list[str] = field(default_factory=lambda: list("lsetropn"))
    fast_digraphs: list[str] = field(default_factory=lambda: [
        "do", "ha", "ve", "nd", "ke", "re", "at", "he", "to", "ma",
        "en", "is", "it", "or", "le", "ti", "se", "ne", "ri", "de",
    ])
    slow_digraphs: list[str] = field(default_factory=lambda: [
        "ov", "li", "an", "ny", "as", "hi", "th", "ng", "lo", "ik",
        "br", "cr", "fr", "gr", "nu", "mu", "un", "ec", "sw", "ce",
        "gy", "my", "by", "rv", "xt", "zy", "hy", "mn",
    ])
    common_words: list[str] = field(default_factory=lambda: [
        "the", "and", "to", "a", "is", "in", "it", "of", "i", "that",
        "you", "for", "was", "on", "are", "but", "not", "my", "this",
        "with", "he", "she", "we", "they", "do", "so", "if", "or", "no",
        "go", "me", "up", "at", "be", "as", "an", "us", "am",
    ])
    text_specific_easy_words: list[str] = field(default_factory=list)
    text_specific_hard_words: list[str] = field(default_factory=list)


@dataclass
class PeekBehavior:
    """Screen-check pause behavior for keyboard peekers."""
    min_chars_before_peek: int = 12
    probability_factor_per_char: float = 0.04
    max_probability: float = 0.50
    pause_duration: Range = field(default_factory=lambda: Range(0.4, 1.2))


@dataclass
class MistakeProfile:
    """Typo generation weights and correction behavior."""
    type_weights: dict[str, int] = field(default_factory=lambda: {
        "adjacent": 55, "transpose_skip": 15, "double": 12,
        "wrong_shift": 10, "drop": 8,
    })
    unnoticed_rate: float = 0.08
    immediate_notice_rate: float = 0.40
    fatigue_error_boost: float = 0.04
    burst_error_multiplier: float = 1.5
    false_alarm_weights: list[int] = field(default_factory=lambda: [75, 25])


@dataclass
class PauseBehavior:
    """Thought pauses and thinking pauses."""
    thought_pause_sentences_interval: IntRange = field(default_factory=lambda: IntRange(2, 4))
    thought_pause_duration: Range = field(default_factory=lambda: Range(2.5, 6.0))
    thinking_pause_probability_factor: float = 0.1
    thinking_pause_lognormal_mu: float = -0.1
    thinking_pause_lognormal_sigma: float = 0.65
    thinking_pause_clamp_min: float = 0.3
    thinking_pause_clamp_max: float = 6.0


@dataclass
class BurstModel:
    """Burst typing probability and fatigue interaction."""
    base_probability: float = 0.025
    post_pause_probability: float = 0.10
    fatigue_multiplier: float = 1.5


@dataclass
class FatigueModel:
    """Fatigue accumulation and recovery."""
    burst_fatigue_multiplier: float = 1.5
    recovery_probability: float = 0.02
    recovery_amount: float = 0.01
    max_level: float = 0.4
    pause_recovery_rate: float = 0.005
    # Feature 7: Backspace accuracy degrades with fatigue
    backspace_miss_base_rate: float = 0.02   # chance of overshooting backspace at zero fatigue
    backspace_miss_fatigue_scale: float = 0.15  # extra miss rate per fatigue_level unit


@dataclass
class CorrectionBehavior:
    """Timing for error corrections and backspacing."""
    quick_correction_pause: Range = field(default_factory=lambda: Range(0.05, 0.15))
    slow_correction_split: float = 0.5
    slow_correction_fast_pause: Range = field(default_factory=lambda: Range(0.20, 0.55))
    slow_correction_slow_pause: Range = field(default_factory=lambda: Range(0.55, 1.20))
    first_backspace_delay: Range = field(default_factory=lambda: Range(0.12, 0.20))
    repeat_backspace_base_lo: float = 0.07
    repeat_backspace_base_hi: float = 0.13
    backspace_acceleration_per_key: float = 0.008
    backspace_acceleration_max: float = 0.03
    post_error_cooldown_chars: IntRange = field(default_factory=lambda: IntRange(4, 8))
    quick_backspace_delay: Range = field(default_factory=lambda: Range(0.03, 0.06))
    quick_pre_retype_pause: Range = field(default_factory=lambda: Range(0.02, 0.06))
    quick_retype_delay: Range = field(default_factory=lambda: Range(0.04, 0.08))
    # Feature 4: Dual-loop error correction
    # Fast loop (motor/automatic) — immediate corrections within ~200ms
    fast_loop_probability: float = 0.35      # chance of fast motor correction
    fast_loop_pause: Range = field(default_factory=lambda: Range(0.08, 0.20))
    fast_loop_backspace_delay: Range = field(default_factory=lambda: Range(0.03, 0.07))
    # Slow loop (cognitive) — delayed corrections with visual search
    slow_loop_search_pause: Range = field(default_factory=lambda: Range(0.30, 0.80))
    slow_loop_per_char_scan: Range = field(default_factory=lambda: Range(0.04, 0.10))


@dataclass
class RewriteBehavior:
    """Rewrite pauses, cascade limits, and density."""
    word_pause: Range = field(default_factory=lambda: Range(0.8, 2.0))
    sentence_pause: Range = field(default_factory=lambda: Range(1.0, 2.5))
    paragraph_pause: Range = field(default_factory=lambda: Range(1.5, 3.5))
    repeat_pause: Range = field(default_factory=lambda: Range(0.5, 1.5))
    repeat_final_pause: Range = field(default_factory=lambda: Range(0.8, 2.0))
    cascade_max_depth: int = 2
    cascade_min_text_length: int = 15
    deep_level_density_reduction: float = 0.5


@dataclass
class ProofreadBehavior:
    """Proofreading and revisit timing."""
    max_proofread_distance: int = 80
    re_reading_pause: Range = field(default_factory=lambda: Range(1.5, 3.5))
    found_typo_pause: Range = field(default_factory=lambda: Range(0.3, 0.8))
    done_sweeping_pause: Range = field(default_factory=lambda: Range(0.2, 0.4))
    revisit_re_reading_pause: Range = field(default_factory=lambda: Range(2.0, 5.0))
    revisit_nav_pause: Range = field(default_factory=lambda: Range(0.3, 0.6))
    revisit_found_spot_pause: Range = field(default_factory=lambda: Range(0.5, 1.5))
    revisit_before_retype_pause: Range = field(default_factory=lambda: Range(0.3, 0.8))
    revisit_jump_back_pause: Range = field(default_factory=lambda: Range(0.3, 0.6))
    revisit_resume_pause: Range = field(default_factory=lambda: Range(0.5, 1.5))
    revisit_min_distance: int = 80
    revisit_length_boost_divisor: float = 3000.0


@dataclass
class MisspellingBehavior:
    """Word-level misspelling notice/correction timing."""
    notice_after_space_probability: float = 0.4
    notice_after_space_pause: Range = field(default_factory=lambda: Range(0.3, 0.8))
    notice_immediately_pause: Range = field(default_factory=lambda: Range(0.2, 0.6))


@dataclass
class OrchestrationTiming:
    """Hardcoded pauses in the orchestrator execution loop."""
    formatting_hotkey_pause: float = 0.1
    navigation_hotkey_pause: Range = field(default_factory=lambda: Range(0.05, 0.10))
    arrow_key_pause: Range = field(default_factory=lambda: Range(0.03, 0.07))
    progress_report_frequency: int = 5


@dataclass
class DistractionConfig:
    """Distraction pause configuration."""
    enabled: bool = True
    probability_per_break_point: float = 0.03
    min_interval_chars: int = 500
    short_weight: float = 0.50
    short_duration: Range = field(default_factory=lambda: Range(15.0, 30.0))
    medium_weight: float = 0.30
    medium_duration: Range = field(default_factory=lambda: Range(45.0, 90.0))
    long_weight: float = 0.15
    long_duration: Range = field(default_factory=lambda: Range(120.0, 180.0))
    very_long_weight: float = 0.05
    very_long_duration: Range = field(default_factory=lambda: Range(180.0, 300.0))


@dataclass
class WordSpeedEntry:
    """Per-word speed adjustment."""
    word: str = ""
    multiplier: float = 1.0
    capital_difficulty: float = 0.0


@dataclass
class AbandonmentConfig:
    """Mid-word abandonment configuration."""
    enabled: bool = True
    probability_per_word: float = 0.02
    max_per_session: int = 3
    pause_before_delete: Range = field(default_factory=lambda: Range(0.4, 1.2))
    pause_before_replacement: Range = field(default_factory=lambda: Range(0.1, 0.3))


@dataclass
class RestructuringConfig:
    """Sentence restructuring configuration."""
    enabled: bool = True
    probability_per_sentence: float = 0.04
    max_per_session: int = 2
    thinking_pause: Range = field(default_factory=lambda: Range(1.5, 4.0))


@dataclass
class FormattingHesitation:
    """Formatting shortcut hesitation configuration."""
    enabled: bool = True
    base_pause: Range = field(default_factory=lambda: Range(0.3, 0.8))
    max_pause: Range = field(default_factory=lambda: Range(3.0, 5.0))
    wrong_shortcut_probability: float = 0.15
    familiarity_ratings: dict[str, float] = field(default_factory=lambda: {
        "bold": 0.9, "italic": 0.8, "underline": 0.7,
        "heading_1": 0.3, "heading_2": 0.3, "heading_3": 0.25,
        "heading_4": 0.2, "heading_5": 0.15, "heading_6": 0.15,
        "numbered_list": 0.5, "bulleted_list": 0.5,
        "align_left": 0.3, "align_center": 0.25,
        "align_right": 0.2, "align_justify": 0.15,
    })


@dataclass
class QuoteConfig:
    """Quote/citation detection and speed configuration."""
    enabled: bool = True
    speed_multiplier: float = 0.55
    paraphrase_speed_multiplier: float = 0.75
    source_glance_frequency: float = 0.08
    source_glance_pause: Range = field(default_factory=lambda: Range(1.0, 3.5))
    misread_rate: float = 0.04
    misread_notice_delay_chars: IntRange = field(default_factory=lambda: IntRange(3, 8))


@dataclass
class AutocorrectConfig:
    """Autocorrect-style mid-flow fix configuration."""
    enabled: bool = True
    probability_per_word: float = 0.08
    max_per_session: int = 4
    min_words_back: int = 2
    max_words_back: int = 6
    notice_pause: Range = field(default_factory=lambda: Range(1.0, 2.5))
    found_word_pause: Range = field(default_factory=lambda: Range(0.3, 0.8))
    before_retype_pause: Range = field(default_factory=lambda: Range(0.2, 0.5))
    return_pause: Range = field(default_factory=lambda: Range(0.3, 0.8))


@dataclass
class FinalProofreadConfig:
    """End-of-session proofreading pass configuration."""
    enabled: bool = True
    probability: float = 0.60
    min_text_length: int = 200
    max_fixes: int = 4
    reading_pause_per_screen: Range = field(default_factory=lambda: Range(1.0, 3.0))
    close_reading_pause: Range = field(default_factory=lambda: Range(3.0, 5.0))
    pre_pass_pause: Range = field(default_factory=lambda: Range(2.0, 4.0))
    found_issue_pause: Range = field(default_factory=lambda: Range(0.5, 1.5))
    before_fix_pause: Range = field(default_factory=lambda: Range(0.2, 0.5))
    chars_per_screen: int = 400


@dataclass
class PreWordPauseConfig:
    """Feature 2: Pre-word pause based on word difficulty."""
    enabled: bool = True
    difficulty_threshold: float = 0.4   # only pause before words with difficulty >= this
    base_pause: Range = field(default_factory=lambda: Range(0.10, 0.30))
    hard_word_pause: Range = field(default_factory=lambda: Range(0.25, 0.60))
    very_hard_word_pause: Range = field(default_factory=lambda: Range(0.50, 1.20))


@dataclass
class CompositionModeConfig:
    """Feature 8: Different timing for composing vs copy-typing."""
    enabled: bool = True
    # Clause boundary pauses — longer pauses when composing thoughts
    clause_pause: Range = field(default_factory=lambda: Range(0.8, 2.5))
    sentence_composition_pause: Range = field(default_factory=lambda: Range(1.5, 4.0))
    # Speed: composing is slower than copy-typing
    composition_speed_multiplier: float = 0.80
    copy_typing_speed_multiplier: float = 1.10


@dataclass
class NewBehaviors:
    """All new AI-driven feature configurations."""
    word_speed_map: list[WordSpeedEntry] = field(default_factory=list)
    distraction: DistractionConfig = field(default_factory=DistractionConfig)
    abandonment: AbandonmentConfig = field(default_factory=AbandonmentConfig)
    restructuring: RestructuringConfig = field(default_factory=RestructuringConfig)
    formatting_hesitation: FormattingHesitation = field(default_factory=FormattingHesitation)
    quote: QuoteConfig = field(default_factory=QuoteConfig)
    autocorrect: AutocorrectConfig = field(default_factory=AutocorrectConfig)
    final_proofread: FinalProofreadConfig = field(default_factory=FinalProofreadConfig)
    pre_word_pause: PreWordPauseConfig = field(default_factory=PreWordPauseConfig)
    composition_mode: CompositionModeConfig = field(default_factory=CompositionModeConfig)


@dataclass
class TypingProfile:
    """AI-generated behavioral fingerprint for a typing session.

    Replaces all hardcoded constants across typing_engine, typing_planner,
    and orchestrator. Generated fresh by AI per paste so no two sessions
    are alike. Falls back to defaults() when AI is unavailable.
    """
    keystroke: KeystrokeTiming = field(default_factory=KeystrokeTiming)
    keys: KeyKnowledge = field(default_factory=KeyKnowledge)
    peek: PeekBehavior = field(default_factory=PeekBehavior)
    mistakes: MistakeProfile = field(default_factory=MistakeProfile)
    pauses: PauseBehavior = field(default_factory=PauseBehavior)
    burst: BurstModel = field(default_factory=BurstModel)
    fatigue: FatigueModel = field(default_factory=FatigueModel)
    correction: CorrectionBehavior = field(default_factory=CorrectionBehavior)
    rewrite: RewriteBehavior = field(default_factory=RewriteBehavior)
    proofread: ProofreadBehavior = field(default_factory=ProofreadBehavior)
    misspelling: MisspellingBehavior = field(default_factory=MisspellingBehavior)
    orchestration: OrchestrationTiming = field(default_factory=OrchestrationTiming)
    behaviors: NewBehaviors = field(default_factory=NewBehaviors)
    # Persona metadata (informational, not consumed by engine)
    persona_description: str = ""
    confidence_level: float = 0.5
    familiarity_with_content: float = 0.5
    energy_level: float = 0.5

    @classmethod
    def defaults(cls) -> "TypingProfile":
        """Current hardcoded values as a profile — used when AI is unavailable."""
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TypingProfile":
        """Build a TypingProfile from a flat or nested dict (e.g. AI JSON response)."""
        profile = cls()
        _apply_dict_to_dataclass(profile, data)
        return profile


def _apply_dict_to_dataclass(obj: Any, data: dict[str, Any]) -> None:
    """Accept only well-typed, bounded profile values from untrusted AI JSON."""
    if not isinstance(data, dict):
        return
    for spec in fields(obj):
        key = spec.name
        if key not in data:
            continue
        value = data[key]
        current = getattr(obj, key)
        if isinstance(current, (Range, IntRange)):
            if not isinstance(value, dict):
                continue
            lo, hi = value.get("min", current.min), value.get("max", current.max)
            integer = isinstance(current, IntRange)
            if (_profile_number(lo, integer=integer) and _profile_number(hi, integer=integer)
                    and 0 <= lo <= hi <= 3600):
                setattr(obj, key, type(current)(lo, hi))
        elif is_dataclass(current):
            if isinstance(value, dict):
                _apply_dict_to_dataclass(current, value)
        elif isinstance(current, bool):
            if isinstance(value, bool):
                setattr(obj, key, value)
        elif isinstance(current, (int, float)):
            if not _profile_number(value, integer=isinstance(current, int)):
                continue
            # Rates and probabilities must remain meaningful. Other positive
            # parameters are capped to keep an accidental AI value bounded.
            probability = (any(part in key for part in ("probability", "rate", "level", "familiarity", "density", "split"))
                           or key in {"confidence_level", "energy_level", "difficulty_threshold"})
            upper = 1 if probability else 3600
            strictly_positive = ("multiplier" in key or key in {"progress_report_frequency", "revisit_length_boost_divisor", "chars_per_screen"})
            if 0 <= value <= upper and (not strictly_positive or value > 0):
                setattr(obj, key, value)
        elif isinstance(current, str):
            if isinstance(value, str):
                setattr(obj, key, value[:2000])
        elif isinstance(current, list):
            if not isinstance(value, list) or len(value) > 1000:
                continue
            if key == "false_alarm_weights":
                if (len(value) == 2 and all(_profile_number(v) and v >= 0 for v in value)
                        and sum(value) > 0):
                    setattr(obj, key, value)
            elif key == "word_speed_map":
                # This metadata is not consumed as timing input by the engine.
                continue
            elif all(isinstance(v, str) for v in value):
                setattr(obj, key, value)
        elif isinstance(current, dict) and isinstance(value, dict):
            allowed = {k: v for k, v in value.items()
                       if k in current and _profile_number(v) and v >= 0}
            if key == "type_weights":
                candidate = {**current, **allowed}
                if sum(candidate.values()) > 0:
                    setattr(obj, key, candidate)
            else:
                current.update({k: min(v, 1) for k, v in allowed.items()})
    # Cross-field invariants consumed by randint() and delay clamping.
    for low, high in (("delay_clamp_min", "delay_clamp_max"),
                      ("thinking_pause_clamp_min", "thinking_pause_clamp_max"),
                      ("min_words_back", "max_words_back")):
        if hasattr(obj, low) and getattr(obj, low) > getattr(obj, high):
            defaults = type(obj)()
            setattr(obj, low, getattr(defaults, low))
            setattr(obj, high, getattr(defaults, high))


def _profile_number(value: Any, *, integer: bool = False) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (not integer or isinstance(value, int)))


# Avoid shadowing built-in max/min inside Range.clamp
import builtins as _builtins
builtins_max = _builtins.max
builtins_min = _builtins.min


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
    speed_multiplier: float = 1.0  # <1 is slower; >1 is faster
    # Planner-only anchor: wrong text, correction, offset within this action.
    proofread_typo: tuple[str, str, int] | None = None

    def __post_init__(self):
        if not math.isfinite(self.speed_multiplier) or self.speed_multiplier <= 0:
            raise ValueError("speed_multiplier must be finite and positive")
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
    """Delete back some characters and retype with new content.

    new_actions is a list of TypingActions to execute after deleting.
    This allows nested rewrites: a Rewrite's new_actions can contain
    further Rewrite actions, creating cascading revision behavior.
    """

    delete_count: int = 0
    new_actions: list[TypingAction] = field(default_factory=list)

    @property
    def new_text(self) -> str:
        """Backward compat: flatten all TypeText actions into a single string."""
        return "".join(
            a.text for a in self.new_actions if isinstance(a, TypeText)
        )

    @staticmethod
    def simple(delete_count: int, text: str, description: str = "") -> "Rewrite":
        """Create a simple rewrite with just text (no nested actions)."""
        return Rewrite(
            delete_count=delete_count,
            new_actions=[TypeText(text=text)],
            description=description,
        )

    def __post_init__(self):
        if not self.description:
            preview = self.new_text[:40] + ("..." if len(self.new_text) > 40 else "")
            self.description = f"Rewrite: delete {self.delete_count} chars, type {preview!r}"


@dataclass
class PressKey(TypingAction):
    """Press a special key (enter, tab, etc.)."""

    key: str = "enter"

    def __post_init__(self):
        if not self.description:
            self.description = f"Press: {self.key}"


@dataclass
class DistractionPause(TypingAction):
    """Extended pause simulating a real-world distraction."""

    duration: float = 30.0
    distraction_type: str = "phone"  # phone, zone_out, social_media, stretch, bathroom, snack

    def __post_init__(self):
        if not self.description:
            self.description = f"Distraction ({self.distraction_type}): {self.duration:.0f}s"


@dataclass
class AbandonWord(TypingAction):
    """Type part of a word, pause, delete it, type a different word."""

    partial_text: str = ""
    replacement_text: str = ""

    def __post_init__(self):
        if not self.description:
            self.description = f"Abandon: {self.partial_text!r} -> {self.replacement_text!r}"


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
    wpm: int = 60
    wpm_variance: int = 12

    # Errors — teen peeker: high raw error rate, notices late
    error_rate: float = 0.12
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

    # Rewriting — cascading rewrite system scaled by paste length
    rewrite_base_probability: float = 0.10   # probability for very short text
    rewrite_max_probability: float = 0.85    # cap for very long text
    rewrite_scaling_chars: int = 2000        # chars at which probability is ~midpoint
    rewrite_word_weight: float = 0.50        # how often word-level rewrites are picked
    rewrite_sentence_weight: float = 0.35    # how often sentence-level rewrites are picked
    rewrite_paragraph_weight: float = 0.15   # how often paragraph-level rewrites are picked
    rewrite_cascade_probability: float = 0.40  # chance a rewrite contains sub-rewrites
    rewrite_repeat_probability: float = 0.15   # chance same spot gets rewritten 2-3x
    rewrite_max_repeats: int = 3

    # Human errors (grammar/punctuation — teen-style, left uncorrected)
    grammar_error_rate: float = 0.15
    punctuation_error_rate: float = 0.20

    # False alarm rate — very rare, teen occasionally second-guesses a correct word
    false_alarm_rate: float = 0.008

    # Proofreading — after a sentence, sometimes arrow back to fix an uncorrected typo
    proofread_probability: float = 0.55

    # Revisiting earlier text — go back to previous paragraphs and revise
    revisit_probability: float = 0.20   # chance per paragraph boundary to go back and revise
    revisit_max_per_session: int = 5    # max revisits per typing session

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
