"""Core typing realism engine for Ghost Typer.

Tuned for a 16-year-old semi-hunt-and-peck typist who peeks at the keyboard,
makes frequent mistakes, and is a bad speller. Not a touch typist — knows
where most keys are but looks down to confirm, especially for uncommon keys,
capitals, numbers, and symbols.

Based on research from:
- Aalto University 136M keystrokes study (Dhakal et al., CHI 2018)
- Keystroke dynamics biometrics research (PMC)
- Rabbitt (1966) post-error slowing effect
"""

from __future__ import annotations

import math
import random
import string
import time
from dataclasses import dataclass, field

from .models import Range, Settings, TypingProfile

# Adjacent keys on QWERTY layout for typo generation
ADJACENT_KEYS: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etdf", "t": "ryfg",
    "y": "tugh", "u": "yijh", "i": "uojk", "o": "iplk", "p": "ol",
    "a": "qwsz", "s": "wedxza", "d": "erfcxs", "f": "rtgvcd",
    "g": "tyhbvf", "h": "yujnbg", "j": "uikmnh", "k": "iolmj",
    "l": "opk", "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb",
    "b": "vghn", "n": "bhjm", "m": "njk",
}

# Feature 5: Finger assignment for each key (QWERTY standard touch-typing)
# pinky=0, ring=1, middle=2, index=3, thumb=4
FINGER_MAP: dict[str, int] = {
    "q": 0, "a": 0, "z": 0, "1": 0, "`": 0,
    "w": 1, "s": 1, "x": 1, "2": 1,
    "e": 2, "d": 2, "c": 2, "3": 2,
    "r": 3, "f": 3, "v": 3, "t": 3, "g": 3, "b": 3, "4": 3, "5": 3,
    "y": 3, "h": 3, "n": 3, "u": 3, "j": 3, "m": 3, "6": 3, "7": 3,
    "i": 2, "k": 2, ",": 2, "8": 2,
    "o": 1, "l": 1, ".": 1, "9": 1,
    "p": 0, ";": 0, "/": 0, "0": 0, "-": 0, "=": 0, "[": 0, "]": 0, "'": 0,
    " ": 4,
}

# Feature 6: Hand assignment (left=0, right=1)
HAND_MAP: dict[str, int] = {
    "q": 0, "w": 0, "e": 0, "r": 0, "t": 0,
    "a": 0, "s": 0, "d": 0, "f": 0, "g": 0,
    "z": 0, "x": 0, "c": 0, "v": 0, "b": 0,
    "1": 0, "2": 0, "3": 0, "4": 0, "5": 0,
    "`": 0,
    "y": 1, "u": 1, "i": 1, "o": 1, "p": 1,
    "h": 1, "j": 1, "k": 1, "l": 1, ";": 1,
    "n": 1, "m": 1, ",": 1, ".": 1, "/": 1,
    "6": 1, "7": 1, "8": 1, "9": 1, "0": 1,
    "-": 1, "=": 1, "[": 1, "]": 1, "'": 1,
    " ": 4,  # thumb — neutral
}


@dataclass
class TypingState:
    """Tracks the mutable state of the engine during a session."""

    chars_typed: int = 0
    chars_since_peek: int = 0       # chars typed since last screen-check
    fatigue_level: float = 0.0
    in_burst: bool = False
    burst_remaining: int = 0
    burst_total: int = 0
    last_pause_at: int = 0
    words_since_pause: int = 0
    current_word: str = ""
    session_start: float = field(default_factory=time.time)
    post_error_cooldown: int = 0
    _effective_wpm: float = 0.0


class TypingEngine:
    """Generates realistic typing timing for a 16-year-old keyboard peeker.

    This kid types with 4-6 fingers, peeks at the keyboard frequently,
    has big WPM swings, and is especially slow on capitals/numbers/symbols.
    """

    def __init__(self, settings: Settings | None = None, profile: TypingProfile | None = None) -> None:
        self.settings = settings or Settings()
        self.profile = profile or TypingProfile.defaults()
        self.state = TypingState()
        self._rng = random.Random()
        self._refresh_effective_wpm()

        # Cache profile key-knowledge sets so we don't rebuild every keystroke
        self._fast_digraphs: set[str] = set(self.profile.keys.fast_digraphs)
        self._slow_digraphs: set[str] = set(self.profile.keys.slow_digraphs)
        self._common_words: set[str] = set(
            self.profile.keys.common_words + self.profile.keys.text_specific_easy_words
        )
        self._common_doubles: set[str] = set(self.profile.keys.common_doubles)
        self._hunt_keys: set[str] = set(self.profile.keys.hunt_keys)

    def _r(self, r: Range) -> float:
        """Sample uniformly from a Range."""
        return self._rng.uniform(r.min, r.max)

    def seed(self, value: int) -> None:
        self._rng.seed(value)

    def reset(self) -> None:
        self.state = TypingState()
        self._refresh_effective_wpm()

    def _refresh_effective_wpm(self) -> None:
        """Resample effective WPM — big swings for an inconsistent typist."""
        self.state._effective_wpm = max(
            10,
            self.settings.wpm + self._rng.gauss(0, self.settings.wpm_variance / 2),
        )

    # ------------------------------------------------------------------
    # Delay calculation
    # ------------------------------------------------------------------

    def base_delay_for_char(self, char: str) -> float:
        """Base IKI for a peeking typist."""
        p = self.profile
        chars_per_second = (self.state._effective_wpm * 5) / 60
        base = 1.0 / chars_per_second

        # Shift key is a BIG deal for a peeker — has to find it, hold it,
        # then find the letter. Much slower than a touch typist.
        if char in string.ascii_uppercase or char in '!@#$%^&*()_+{}|:"<>?~':
            base *= self._r(p.keystroke.shift_multiplier)

        # Numbers and symbols: hunting on the number row
        if char in '.?!':
            base *= self._r(p.keystroke.end_punctuation_multiplier)
        elif char in ',;:':
            base *= self._r(p.keystroke.mid_punctuation_multiplier)
        elif char in string.digits:
            base *= self._r(p.keystroke.digit_multiplier)
        elif char in string.punctuation:
            base *= self._r(p.keystroke.symbol_multiplier)

        # Hunt keys (z, x, q, j, k, v) — less familiar positions
        if char.lower() in self._hunt_keys:
            base *= self._r(p.keystroke.hunt_key_multiplier)

        return base

    def delay_for_keystroke(self, char: str, prev_char: str = "") -> float:
        """Full delay with all the quirks of a teenage keyboard peeker."""
        p = self.profile
        base = self.base_delay_for_char(char)

        # --- Feature 1: Bimodal IKI distribution ---
        # Two modes: fast (automatized, tight spread) and slow (hunt, wide spread)
        if self._rng.random() < p.keystroke.bimodal_fast_probability:
            jitter = self._rng.lognormvariate(0, p.keystroke.bimodal_fast_sigma)
        else:
            jitter = self._rng.lognormvariate(0, p.keystroke.bimodal_slow_sigma)
            base *= p.keystroke.bimodal_slow_multiplier
        base *= jitter

        # --- Session warmup (first ~N chars settling in) ---
        if self.state.chars_typed < p.keystroke.warmup_chars:
            warmup_factor = 1.0 + p.keystroke.warmup_slowdown * (
                1.0 - self.state.chars_typed / p.keystroke.warmup_chars
            )
            base *= warmup_factor

        # --- Intra-word: first char slow (looking for it), middle chars ok ---
        word_len = len(self.state.current_word)
        if char not in (" ", "\n", "\t"):
            if word_len == 0:
                # First char: finding the key, motor planning
                base *= self._r(p.keystroke.first_char_of_word_multiplier)
            elif word_len <= 2:
                base *= self._r(p.keystroke.early_word_multiplier)
            else:
                # Mid-word: got some rhythm going
                base *= self._r(p.keystroke.mid_word_multiplier)

        # --- Digraph timing (reduced effect — peeker doesn't have strong muscle memory) ---
        if prev_char:
            digraph = (prev_char + char).lower()
            if digraph in self._fast_digraphs:
                base *= self._r(p.keystroke.fast_digraph_multiplier)
            elif digraph in self._slow_digraphs:
                base *= self._r(p.keystroke.slow_digraph_multiplier)

        # --- Common word boost (only for very basic words) ---
        if self.state.current_word.lower() in self._common_words:
            if len(self.state.current_word) <= 1:
                base *= self._r(p.keystroke.common_word_short_multiplier)
            else:
                base *= self._r(p.keystroke.common_word_long_multiplier)

        # --- Burst typing ---
        if self.state.in_burst:
            total = max(self.state.burst_total, 1)
            progress = 1.0 - (self.state.burst_remaining / total)
            if progress < 0.2:
                envelope = 0.5 + progress * 2.5
            elif progress > 0.8:
                envelope = 0.5 + (1.0 - progress) * 2.5
            else:
                envelope = 1.0
            effective_mult = 1.0 + (self.settings.burst_speed_multiplier - 1.0) * envelope
            base *= 1.0 / effective_mult
            self.state.burst_remaining -= 1
            if self.state.burst_remaining <= 0:
                self.state.in_burst = False

        # --- Fatigue ---
        if self.settings.fatigue_enabled:
            base *= 1.0 + self.state.fatigue_level

        # --- Same-key repeat ---
        if prev_char and char.lower() == prev_char.lower():
            if char.lower() in self._common_doubles:
                base *= self._r(p.keystroke.common_double_multiplier)
            else:
                base *= self._r(p.keystroke.uncommon_double_multiplier)

        # --- Feature 5: Finger-specific speed ---
        finger = FINGER_MAP.get(char.lower(), -1)
        if finger == 0:
            base *= p.keystroke.finger_pinky_multiplier
        elif finger == 1:
            base *= p.keystroke.finger_ring_multiplier
        elif finger == 2:
            base *= p.keystroke.finger_middle_multiplier
        elif finger == 3:
            base *= p.keystroke.finger_index_multiplier
        # thumb (4) uses thumb_multiplier but it's 1.0 by default

        # --- Feature 6: Hand alternation ---
        if prev_char:
            cur_hand = HAND_MAP.get(char.lower(), -1)
            prev_hand = HAND_MAP.get(prev_char.lower(), -1)
            if cur_hand >= 0 and prev_hand >= 0 and cur_hand != 4 and prev_hand != 4:
                if cur_hand != prev_hand:
                    base *= p.keystroke.hand_alternation_multiplier
                else:
                    # Same hand — check if same finger too
                    cur_finger = FINGER_MAP.get(char.lower(), -1)
                    prev_finger = FINGER_MAP.get(prev_char.lower(), -1)
                    if cur_finger == prev_finger and cur_finger >= 0:
                        base *= p.keystroke.same_finger_multiplier
                    else:
                        base *= p.keystroke.same_hand_multiplier

        # --- Space / word boundary ---
        if char == " ":
            if self._rng.random() < p.keystroke.space_thinking_probability:
                base *= self._r(p.keystroke.space_thinking_multiplier)
            else:
                base *= self._r(p.keystroke.space_normal_multiplier)

        # --- Enter key ---
        if char == "\n":
            base *= self._r(p.keystroke.enter_multiplier)

        # --- Post-error slowdown (bigger effect — kid gets flustered) ---
        if self.state.post_error_cooldown > 0:
            base *= self._r(p.keystroke.post_error_multiplier)
            self.state.post_error_cooldown -= 1

        # Clamp — allow hesitations up to max (peeker sometimes just stares at keyboard)
        return max(p.keystroke.delay_clamp_min, min(base, p.keystroke.delay_clamp_max))

    def should_peek_pause(self) -> bool:
        """Should the typist pause to look up at the screen?

        A keyboard peeker types a chunk while looking down, then looks up
        to check what appeared on screen. This creates distinctive periodic
        pauses every ~15-35 characters.
        """
        p = self.profile
        if self.state.chars_since_peek < p.peek.min_chars_before_peek:
            return False
        # Probability increases the longer since last peek
        prob = (self.state.chars_since_peek - p.peek.min_chars_before_peek) * p.peek.probability_factor_per_char
        return self._rng.random() < min(prob, p.peek.max_probability)

    def peek_pause_duration(self) -> float:
        """How long the screen-check pause lasts."""
        # Quick glance up, verify text, look back down
        return self._r(self.profile.peek.pause_duration)

    def should_thinking_pause(self) -> bool:
        return self._rng.random() < self.settings.pause_frequency * self.profile.pauses.thinking_pause_probability_factor

    def thinking_pause_duration(self) -> float:
        """Log-normal: mostly short, occasionally long."""
        p = self.profile
        return max(
            p.pauses.thinking_pause_clamp_min,
            min(
                self._rng.lognormvariate(p.pauses.thinking_pause_lognormal_mu, p.pauses.thinking_pause_lognormal_sigma),
                p.pauses.thinking_pause_clamp_max,
            ),
        )

    def sentence_pause_duration(self) -> float:
        return self._rng.uniform(
            self.settings.sentence_pause_min,
            self.settings.sentence_pause_max,
        )

    def paragraph_pause_duration(self) -> float:
        return self._rng.uniform(
            self.settings.paragraph_pause_min,
            self.settings.paragraph_pause_max,
        )

    # ------------------------------------------------------------------
    # Burst typing
    # ------------------------------------------------------------------

    def maybe_start_burst(self) -> None:
        if not self.settings.burst_typing_enabled:
            return
        if self.state.in_burst:
            return
        # Peekers burst less often and shorter
        p = self.profile
        base_prob = p.burst.base_probability
        if self.state.words_since_pause <= 1:
            base_prob = p.burst.post_pause_probability
        if self._rng.random() < base_prob:
            self.state.in_burst = True
            length = self._rng.randint(
                self.settings.burst_length_min,
                self.settings.burst_length_max,
            )
            self.state.burst_remaining = length
            self.state.burst_total = length

    # ------------------------------------------------------------------
    # Fatigue
    # ------------------------------------------------------------------

    def update_fatigue(self) -> None:
        if not self.settings.fatigue_enabled:
            return
        p = self.profile
        if self.state.in_burst:
            self.state.fatigue_level += self.settings.fatigue_rate * p.fatigue.burst_fatigue_multiplier
        else:
            self.state.fatigue_level += self.settings.fatigue_rate
        if self._rng.random() < p.fatigue.recovery_probability:
            self.state.fatigue_level = max(0, self.state.fatigue_level - p.fatigue.recovery_amount)
        self.state.fatigue_level = min(self.state.fatigue_level, p.fatigue.max_level)

    def recover_fatigue_during_pause(self, pause_seconds: float) -> None:
        if not self.settings.fatigue_enabled:
            return
        recovery = pause_seconds * self.profile.fatigue.pause_recovery_rate
        self.state.fatigue_level = max(0, self.state.fatigue_level - recovery)

    # ------------------------------------------------------------------
    # Mistake generation
    # ------------------------------------------------------------------

    def should_make_mistake(self) -> bool:
        p = self.profile
        rate = self.settings.error_rate
        if self.settings.fatigue_enabled:
            rate += self.state.fatigue_level * p.mistakes.fatigue_error_boost
        if self.state.in_burst:
            rate *= p.mistakes.burst_error_multiplier
        return self._rng.random() < rate

    def should_false_alarm(self) -> bool:
        return self._rng.random() < self.settings.false_alarm_rate

    def false_alarm_chars(self) -> int:
        return self._rng.choices([1, 2], weights=self.profile.mistakes.false_alarm_weights, k=1)[0]

    def generate_typo(self, intended_char: str) -> str:
        lower = intended_char.lower()
        tw = self.profile.mistakes.type_weights
        typo_types = list(tw.keys())
        typo_weights = list(tw.values())
        typo_type = self._rng.choices(
            typo_types,
            weights=typo_weights,
            k=1,
        )[0]

        if typo_type == "adjacent" and lower in ADJACENT_KEYS:
            neighbors = ADJACENT_KEYS[lower]
            replacement = self._rng.choice(neighbors)
            if intended_char.isupper():
                replacement = replacement.upper()
            return replacement

        if typo_type == "double":
            return intended_char + intended_char

        if typo_type == "wrong_shift":
            if intended_char.isupper():
                return intended_char.lower()
            if intended_char.islower():
                return intended_char.upper()
            return intended_char

        if typo_type == "drop":
            return ""

        if lower.isalpha():
            offset = self._rng.choice([-1, 1])
            new_ord = ord(lower) + offset
            if ord("a") <= new_ord <= ord("z"):
                c = chr(new_ord)
                return c.upper() if intended_char.isupper() else c

        return intended_char

    def chars_before_noticing_mistake(self) -> int:
        """Peekers notice mistakes later — they're looking at the keyboard, not the screen."""
        if self._rng.random() < self.profile.mistakes.immediate_notice_rate:
            return 0
        lo, hi = self.settings.correction_delay_chars
        if hi <= 0:
            return 0
        return self._rng.randint(max(1, min(lo, hi)), hi)

    def rewrite_probability_for_length(self, total_chars: int) -> float:
        """Sigmoid scaling: short text = rare rewrites, long text = frequent."""
        base = self.settings.rewrite_base_probability
        max_p = self.settings.rewrite_max_probability
        mid = self.settings.rewrite_scaling_chars
        x = (total_chars - mid / 2) / max(mid / 4, 1)
        sigmoid = 1.0 / (1.0 + math.exp(-x))
        return base + (max_p - base) * sigmoid

    def should_rewrite(self, total_chars: int = 500) -> bool:
        prob = self.rewrite_probability_for_length(total_chars)
        return self._rng.random() < prob

    def pick_rewrite_granularity(self) -> str:
        """Choose word, sentence, or paragraph level rewrite."""
        return self._rng.choices(
            ["word", "sentence", "paragraph"],
            weights=[
                self.settings.rewrite_word_weight,
                self.settings.rewrite_sentence_weight,
                self.settings.rewrite_paragraph_weight,
            ],
            k=1,
        )[0]

    def should_cascade(self) -> bool:
        return self._rng.random() < self.settings.rewrite_cascade_probability

    def should_repeat_rewrite(self) -> bool:
        return self._rng.random() < self.settings.rewrite_repeat_probability

    def rewrite_word_count(self) -> int:
        if self._rng.random() < 0.4:
            return self._rng.randint(4, 8)
        return self._rng.randint(1, 5)

    # ------------------------------------------------------------------
    # Correction timing
    # ------------------------------------------------------------------

    def correction_pause_duration(self) -> float:
        """Peekers have longer correction pauses — have to look up at screen,
        find the error, then look back down at keyboard."""
        p = self.profile
        if self._rng.random() < p.correction.slow_correction_split:
            return self._r(p.correction.slow_correction_fast_pause)
        else:
            return self._r(p.correction.slow_correction_slow_pause)

    def backspace_delay(self, nth_backspace: int = 0) -> float:
        """First backspace slow (finding it), then faster."""
        p = self.profile
        if nth_backspace == 0:
            return self._r(p.correction.first_backspace_delay)
        else:
            accel = min(nth_backspace * p.correction.backspace_acceleration_per_key, p.correction.backspace_acceleration_max)
            base_lo = max(0.05, p.correction.repeat_backspace_base_lo - accel)
            base_hi = max(0.07, p.correction.repeat_backspace_base_hi - accel)
            return self._rng.uniform(base_lo, base_hi)

    def should_backspace_overshoot(self) -> bool:
        """Feature 7: Fatigued typists sometimes overshoot backspace (delete one extra)."""
        p = self.profile
        miss_rate = (
            p.fatigue.backspace_miss_base_rate
            + self.state.fatigue_level * p.fatigue.backspace_miss_fatigue_scale
        )
        return self._rng.random() < miss_rate

    def on_error_corrected(self) -> None:
        """Post-error caution — bigger effect for a peeker (gets flustered)."""
        p = self.profile
        self.state.post_error_cooldown = self._rng.randint(
            p.correction.post_error_cooldown_chars.min,
            p.correction.post_error_cooldown_chars.max,
        )

    def is_fast_loop_correction(self) -> bool:
        """Feature 4: Decide if this correction uses fast (motor) or slow (cognitive) loop."""
        return self._rng.random() < self.profile.correction.fast_loop_probability

    def fast_loop_pause(self) -> float:
        """Feature 4: Quick motor correction pause (~100-200ms)."""
        return self._r(self.profile.correction.fast_loop_pause)

    def slow_loop_search_pause(self, chars_back: int) -> float:
        """Feature 4: Slow cognitive correction — visual search time scales with distance."""
        p = self.profile
        base = self._r(p.correction.slow_loop_search_pause)
        per_char = self._r(p.correction.slow_loop_per_char_scan) * chars_back
        return base + per_char

    # ------------------------------------------------------------------
    # Word tracking
    # ------------------------------------------------------------------

    def on_char_typed(self, char: str) -> None:
        self.state.chars_typed += 1
        self.state.chars_since_peek += 1
        if char == " " or char == "\n":
            self.state.current_word = ""
            self.state.words_since_pause += 1
            self._refresh_effective_wpm()
            self.maybe_start_burst()
        else:
            self.state.current_word += char
        self.update_fatigue()

    def on_pause(self) -> None:
        self.state.words_since_pause = 0

    def on_peek(self) -> None:
        """Reset the peek counter after a screen-check pause."""
        self.state.chars_since_peek = 0
