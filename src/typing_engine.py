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

from .models import Settings

# Adjacent keys on QWERTY layout for typo generation
ADJACENT_KEYS: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etdf", "t": "ryfg",
    "y": "tugh", "u": "yijh", "i": "uojk", "o": "iplk", "p": "ol",
    "a": "qwsz", "s": "wedxza", "d": "erfcxs", "f": "rtgvcd",
    "g": "tyhbvf", "h": "yujnbg", "j": "uikmnh", "k": "iolmj",
    "l": "opk", "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb",
    "b": "vghn", "n": "bhjm", "m": "njk",
}

# Fast digraphs — but reduced effect for a peeker (less muscle memory)
FAST_DIGRAPHS: set[str] = {
    "do", "ha", "ve", "nd", "ke", "re", "at", "he", "to", "ma",
    "en", "is", "it", "or", "le", "ti", "se", "ne", "ri", "de",
}

# Slow digraphs — same finger or awkward reaches (bigger penalty for peekers)
SLOW_DIGRAPHS: set[str] = {
    "ov", "li", "an", "ny", "as", "hi", "th", "ng", "lo", "ik",
    "br", "cr", "fr", "gr", "nu", "mu", "un", "ec", "sw", "ce",
    "gy", "my", "by", "rv", "xt", "zy", "hy", "mn",
}

# Only the most basic words are truly muscle-memorized for a peeking typist
COMMON_WORDS: set[str] = {
    "the", "and", "to", "a", "is", "in", "it", "of", "i", "that",
    "you", "for", "was", "on", "are", "but", "not", "my", "this",
    "with", "he", "she", "we", "they", "do", "so", "if", "or", "no",
    "go", "me", "up", "at", "be", "as", "an", "us", "am",
}

# Common English double letters
COMMON_DOUBLES: set[str] = set("lsetropn")

# Keys that require hunting (not on home row or common reach)
# A peeking typist knows QWERTY layout roughly but hunts for these
HUNT_KEYS: set[str] = set("zxqjkv")


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

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.state = TypingState()
        self._rng = random.Random()
        self._refresh_effective_wpm()

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
        chars_per_second = (self.state._effective_wpm * 5) / 60
        base = 1.0 / chars_per_second

        # Shift key is a BIG deal for a peeker — has to find it, hold it,
        # then find the letter. Much slower than a touch typist.
        if char in string.ascii_uppercase or char in '!@#$%^&*()_+{}|:"<>?~':
            base *= self._rng.uniform(1.40, 2.00)

        # Numbers and symbols: hunting on the number row
        if char in '.?!':
            base *= self._rng.uniform(1.20, 1.45)
        elif char in ',;:':
            base *= self._rng.uniform(1.15, 1.40)
        elif char in string.digits:
            base *= self._rng.uniform(1.50, 2.20)  # really has to hunt
        elif char in string.punctuation:
            base *= self._rng.uniform(1.30, 1.80)  # symbols are hard

        # Hunt keys (z, x, q, j, k, v) — less familiar positions
        if char.lower() in HUNT_KEYS:
            base *= self._rng.uniform(1.15, 1.40)

        return base

    def delay_for_keystroke(self, char: str, prev_char: str = "") -> float:
        """Full delay with all the quirks of a teenage keyboard peeker."""
        base = self.base_delay_for_char(char)

        # --- Jitter: WIDE spread for an inconsistent typist ---
        # sigma=0.30 gives very variable timing (sometimes fast, sometimes slow)
        jitter = self._rng.lognormvariate(0, 0.30)
        base *= jitter

        # --- Session warmup (first ~15 chars settling in) ---
        if self.state.chars_typed < 15:
            warmup_factor = 1.0 + 0.20 * (1.0 - self.state.chars_typed / 15.0)
            base *= warmup_factor

        # --- Intra-word: first char slow (looking for it), middle chars ok ---
        word_len = len(self.state.current_word)
        if char not in (" ", "\n", "\t"):
            if word_len == 0:
                # First char: finding the key, motor planning
                base *= self._rng.uniform(1.15, 1.40)
            elif word_len <= 2:
                base *= self._rng.uniform(0.95, 1.10)
            else:
                # Mid-word: got some rhythm going
                base *= self._rng.uniform(0.88, 0.98)

        # --- Digraph timing (reduced effect — peeker doesn't have strong muscle memory) ---
        if prev_char:
            digraph = (prev_char + char).lower()
            if digraph in FAST_DIGRAPHS:
                base *= self._rng.uniform(0.88, 0.96)  # smaller boost than touch typist
            elif digraph in SLOW_DIGRAPHS:
                base *= self._rng.uniform(1.08, 1.25)

        # --- Common word boost (only for very basic words) ---
        if self.state.current_word.lower() in COMMON_WORDS:
            if len(self.state.current_word) <= 1:
                base *= self._rng.uniform(0.80, 0.90)
            else:
                base *= self._rng.uniform(0.93, 0.99)

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
            if char.lower() in COMMON_DOUBLES:
                base *= self._rng.uniform(0.85, 0.95)
            else:
                base *= self._rng.uniform(0.95, 1.12)

        # --- Space / word boundary ---
        if char == " ":
            if self._rng.random() < 0.70:
                base *= self._rng.uniform(1.0, 1.4)
            else:
                base *= self._rng.uniform(1.8, 3.5)  # looking at screen or thinking

        # --- Enter key ---
        if char == "\n":
            base *= self._rng.uniform(1.4, 2.0)

        # --- Post-error slowdown (bigger effect — kid gets flustered) ---
        if self.state.post_error_cooldown > 0:
            base *= self._rng.uniform(1.12, 1.35)
            self.state.post_error_cooldown -= 1

        # Clamp — allow hesitations up to 2s (peeker sometimes just stares at keyboard)
        return max(0.035, min(base, 2.000))

    def should_peek_pause(self) -> bool:
        """Should the typist pause to look up at the screen?

        A keyboard peeker types a chunk while looking down, then looks up
        to check what appeared on screen. This creates distinctive periodic
        pauses every ~15-35 characters.
        """
        if self.state.chars_since_peek < 12:
            return False
        # Probability increases the longer since last peek
        prob = (self.state.chars_since_peek - 12) * 0.04
        return self._rng.random() < min(prob, 0.5)

    def peek_pause_duration(self) -> float:
        """How long the screen-check pause lasts."""
        # Quick glance up, verify text, look back down
        return self._rng.uniform(0.4, 1.2)

    def should_thinking_pause(self) -> bool:
        return self._rng.random() < self.settings.pause_frequency * 0.1

    def thinking_pause_duration(self) -> float:
        """Log-normal: mostly short, occasionally long."""
        return max(0.3, min(self._rng.lognormvariate(-0.1, 0.65), 6.0))

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
        base_prob = 0.025
        if self.state.words_since_pause <= 1:
            base_prob = 0.10
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
        if self.state.in_burst:
            self.state.fatigue_level += self.settings.fatigue_rate * 1.5
        else:
            self.state.fatigue_level += self.settings.fatigue_rate
        if self._rng.random() < 0.02:
            self.state.fatigue_level = max(0, self.state.fatigue_level - 0.01)
        self.state.fatigue_level = min(self.state.fatigue_level, 0.4)

    def recover_fatigue_during_pause(self, pause_seconds: float) -> None:
        if not self.settings.fatigue_enabled:
            return
        recovery = pause_seconds * 0.005
        self.state.fatigue_level = max(0, self.state.fatigue_level - recovery)

    # ------------------------------------------------------------------
    # Mistake generation
    # ------------------------------------------------------------------

    def should_make_mistake(self) -> bool:
        rate = self.settings.error_rate
        if self.settings.fatigue_enabled:
            rate += self.state.fatigue_level * 0.04  # fatigue hits peekers harder
        if self.state.in_burst:
            rate *= 1.5  # bursting = more sloppy
        return self._rng.random() < rate

    def should_false_alarm(self) -> bool:
        return self._rng.random() < self.settings.false_alarm_rate

    def false_alarm_chars(self) -> int:
        return self._rng.choices([1, 2], weights=[75, 25], k=1)[0]

    def generate_typo(self, intended_char: str) -> str:
        lower = intended_char.lower()
        typo_type = self._rng.choices(
            ["adjacent", "transpose_skip", "double", "wrong_shift", "drop"],
            weights=[55, 15, 12, 10, 8],
            k=1,
        )[0]

        if typo_type == "adjacent" and lower in ADJACENT_KEYS:
            neighbors = ADJACENT_KEYS[lower]
            replacement = self._rng.choice(neighbors)
            if intended_char.isupper():
                replacement = replacement.upper()
            return replacement

        if typo_type == "double":
            return intended_char

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
        # 40% immediate (felt the wrong key), 60% delayed
        if self._rng.random() < 0.40:
            return 0
        lo, hi = self.settings.correction_delay_chars
        return self._rng.randint(max(lo, 1), hi)

    def should_rewrite(self) -> bool:
        return self._rng.random() < self.settings.rewrite_probability

    def rewrite_word_count(self) -> int:
        max_w = self.settings.rewrite_max_words
        if max_w > 6 and self._rng.random() < 0.4:
            return self._rng.randint(6, max_w)
        return self._rng.randint(1, min(5, max_w))

    # ------------------------------------------------------------------
    # Correction timing
    # ------------------------------------------------------------------

    def correction_pause_duration(self) -> float:
        """Peekers have longer correction pauses — have to look up at screen,
        find the error, then look back down at keyboard."""
        if self._rng.random() < 0.5:
            return self._rng.uniform(0.20, 0.55)
        else:
            return self._rng.uniform(0.55, 1.20)  # really studying the screen

    def backspace_delay(self, nth_backspace: int = 0) -> float:
        """First backspace slow (finding it), then faster."""
        if nth_backspace == 0:
            return self._rng.uniform(0.12, 0.20)
        else:
            accel = min(nth_backspace * 0.008, 0.03)
            base_lo = max(0.05, 0.07 - accel)
            base_hi = max(0.07, 0.13 - accel)
            return self._rng.uniform(base_lo, base_hi)

    def on_error_corrected(self) -> None:
        """Post-error caution — bigger effect for a peeker (gets flustered)."""
        self.state.post_error_cooldown = self._rng.randint(4, 8)

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
