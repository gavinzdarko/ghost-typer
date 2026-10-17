#!/usr/bin/env python3
"""
Ghost Typer — Typing Profiler

Records exactly how you type, then generates a typing profile that Ghost Typer
can use to mimic your style. Captures:

  - Inter-key intervals (per character class and digraph)
  - WPM over time (average, variance, burst patterns)
  - Error/correction behavior (how often, how fast, how far back)
  - Pause patterns (thinking pauses, sentence pauses, paragraph pauses)
  - Fatigue curve over the session

Run this, type naturally for a few minutes, then press ESC to finish.
It will analyze your typing and save a profile.

Usage:
    python3 typing_profiler.py [--prompt FILE]

    --prompt FILE   Show text from FILE for you to type (optional).
                    Without this, you type freely (freeform mode).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

try:
    from pynput import keyboard
except ImportError:
    print("ERROR: pynput is required. Install it:  pip install pynput")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

@dataclass
class KeyEvent:
    """A single keystroke event."""
    timestamp: float
    char: str           # the character typed (or special key name)
    is_backspace: bool = False
    is_enter: bool = False
    is_space: bool = False
    is_shift: bool = False  # was shift held


@dataclass
class CorrectionEvent:
    """A detected error correction (backspace sequence)."""
    timestamp: float
    chars_deleted: int
    pause_before: float     # pause between last char and first backspace
    pause_after: float      # pause between last backspace and next char
    backspace_intervals: list[float] = field(default_factory=list)


@dataclass
class PauseEvent:
    """A detected pause in typing."""
    timestamp: float
    duration: float
    after_char: str         # what character preceded the pause
    context: str            # "mid_word", "word_boundary", "sentence", "paragraph"


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

class TypingRecorder:
    """Captures raw keystrokes with timestamps."""

    def __init__(self) -> None:
        self.events: list[KeyEvent] = []
        self._start_time: float = 0.0
        self._shift_held = False
        self._done = False
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        self._start_time = time.time()
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        self._done = True
        if self._listener:
            self._listener.stop()

    @property
    def is_done(self) -> bool:
        return self._done

    def _on_press(self, key) -> None:
        now = time.time()

        # ESC = finish recording
        if key == keyboard.Key.esc:
            self._done = True
            return False  # stop listener

        if key in (keyboard.Key.shift, keyboard.Key.shift_r):
            self._shift_held = True
            return

        event = KeyEvent(timestamp=now, char="", is_shift=self._shift_held)

        if key == keyboard.Key.backspace:
            event.char = "<BS>"
            event.is_backspace = True
        elif key == keyboard.Key.enter:
            event.char = "\n"
            event.is_enter = True
        elif key == keyboard.Key.space:
            event.char = " "
            event.is_space = True
        elif key == keyboard.Key.tab:
            event.char = "\t"
        elif hasattr(key, "char") and key.char:
            event.char = key.char
        else:
            return  # ignore other special keys

        self.events.append(event)

    def _on_release(self, key) -> None:
        if key in (keyboard.Key.shift, keyboard.Key.shift_r):
            self._shift_held = False


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

SENTENCE_ENDERS = set(".!?")
PARAGRAPH_PAUSE_THRESHOLD = 3.0  # seconds
SENTENCE_PAUSE_THRESHOLD = 1.0
THINKING_PAUSE_THRESHOLD = 0.5
BURST_SPEED_RATIO = 0.65  # intervals below this * median = "burst"


class TypingAnalyzer:
    """Analyzes recorded keystrokes to extract a typing profile."""

    def __init__(self, events: list[KeyEvent]) -> None:
        self.events = events
        self.intervals: list[float] = []
        self.digraph_intervals: dict[str, list[float]] = defaultdict(list)
        self.char_intervals: dict[str, list[float]] = defaultdict(list)
        self.corrections: list[CorrectionEvent] = []
        self.pauses: list[PauseEvent] = []
        self.word_wpms: list[float] = []
        self.burst_lengths: list[int] = []
        self.burst_speeds: list[float] = []  # chars/sec during bursts
        self.rolling_wpms: list[float] = []  # WPM in sliding windows

    def analyze(self) -> dict:
        """Run full analysis and return a profile dict."""
        if len(self.events) < 10:
            print("Not enough keystrokes to analyze.")
            sys.exit(1)

        self._compute_intervals()
        self._detect_corrections()
        self._detect_pauses()
        self._compute_word_wpms()
        self._detect_bursts()
        self._compute_rolling_wpm()

        return self._build_profile()

    def _compute_intervals(self) -> None:
        """Compute inter-key intervals and per-digraph/char timings."""
        typing_events = [e for e in self.events if not e.is_backspace]
        for i in range(1, len(typing_events)):
            prev = typing_events[i - 1]
            curr = typing_events[i]
            dt = curr.timestamp - prev.timestamp

            # Skip huge pauses for interval stats (those are "pauses", not typing speed)
            if dt > 5.0:
                continue

            self.intervals.append(dt)

            # Per-character class
            cls = _char_class(curr.char)
            self.char_intervals[cls].append(dt)

            # Digraph
            if prev.char and curr.char and len(prev.char) == 1 and len(curr.char) == 1:
                digraph = (prev.char + curr.char).lower()
                self.digraph_intervals[digraph].append(dt)

    def _detect_corrections(self) -> None:
        """Find backspace sequences and measure correction behavior."""
        i = 0
        while i < len(self.events):
            if self.events[i].is_backspace:
                # Start of a correction
                bs_start = i
                bs_count = 0
                bs_intervals = []

                while i < len(self.events) and self.events[i].is_backspace:
                    if bs_count > 0:
                        bs_intervals.append(
                            self.events[i].timestamp - self.events[i - 1].timestamp
                        )
                    bs_count += 1
                    i += 1

                # Pause before correction
                pause_before = 0.0
                if bs_start > 0:
                    pause_before = (
                        self.events[bs_start].timestamp
                        - self.events[bs_start - 1].timestamp
                    )

                # Pause after correction (before next char)
                pause_after = 0.0
                if i < len(self.events):
                    pause_after = (
                        self.events[i].timestamp
                        - self.events[i - 1].timestamp
                    )

                self.corrections.append(CorrectionEvent(
                    timestamp=self.events[bs_start].timestamp,
                    chars_deleted=bs_count,
                    pause_before=pause_before,
                    pause_after=pause_after,
                    backspace_intervals=bs_intervals,
                ))
            else:
                i += 1

    def _detect_pauses(self) -> None:
        """Find significant pauses and classify them."""
        typing_events = [e for e in self.events if not e.is_backspace]
        for i in range(1, len(typing_events)):
            prev = typing_events[i - 1]
            curr = typing_events[i]
            dt = curr.timestamp - prev.timestamp

            if dt < THINKING_PAUSE_THRESHOLD:
                continue

            # Classify
            if prev.char in SENTENCE_ENDERS and curr.char == " ":
                if dt >= PARAGRAPH_PAUSE_THRESHOLD:
                    context = "paragraph"
                else:
                    context = "sentence"
            elif prev.is_enter:
                context = "paragraph"
            elif prev.is_space or curr.is_space:
                context = "word_boundary"
            else:
                context = "mid_word"

            self.pauses.append(PauseEvent(
                timestamp=prev.timestamp,
                duration=dt,
                after_char=prev.char,
                context=context,
            ))

    def _compute_word_wpms(self) -> None:
        """Compute WPM for each word typed."""
        typing_events = [e for e in self.events if not e.is_backspace]
        word_chars = 0
        word_start_time = typing_events[0].timestamp if typing_events else 0

        for e in typing_events:
            if e.is_space or e.is_enter:
                if word_chars > 0:
                    duration = e.timestamp - word_start_time
                    if duration > 0.01:
                        # WPM = (chars / 5) / (duration / 60)
                        wpm = (word_chars / 5) / (duration / 60)
                        if wpm < 200:  # sanity
                            self.word_wpms.append(wpm)
                word_chars = 0
                word_start_time = e.timestamp
            elif len(e.char) == 1:
                word_chars += 1

    def _detect_bursts(self) -> None:
        """Find bursts of fast typing."""
        if not self.intervals:
            return

        median_interval = statistics.median(self.intervals)
        burst_threshold = median_interval * BURST_SPEED_RATIO

        current_burst = 0
        burst_intervals = []

        for dt in self.intervals:
            if dt < burst_threshold:
                current_burst += 1
                burst_intervals.append(dt)
            else:
                if current_burst >= 3:
                    self.burst_lengths.append(current_burst)
                    avg = statistics.mean(burst_intervals)
                    self.burst_speeds.append(1.0 / avg if avg > 0 else 0)
                current_burst = 0
                burst_intervals = []

        if current_burst >= 3:
            self.burst_lengths.append(current_burst)
            avg = statistics.mean(burst_intervals)
            self.burst_speeds.append(1.0 / avg if avg > 0 else 0)

    def _compute_rolling_wpm(self) -> None:
        """Compute WPM in 10-second sliding windows."""
        typing_events = [e for e in self.events if not e.is_backspace]
        if len(typing_events) < 5:
            return

        window = 10.0  # seconds
        start = typing_events[0].timestamp
        end = typing_events[-1].timestamp

        t = start
        while t + window <= end:
            chars_in_window = sum(
                1 for e in typing_events
                if t <= e.timestamp < t + window and len(e.char) == 1
            )
            wpm = (chars_in_window / 5) / (window / 60)
            self.rolling_wpms.append(wpm)
            t += 5.0  # step by 5 seconds

    def _build_profile(self) -> dict:
        """Build the final profile from all collected stats."""
        total_duration = self.events[-1].timestamp - self.events[0].timestamp
        typing_events = [e for e in self.events if not e.is_backspace]
        total_chars = len(typing_events)

        # --- WPM ---
        if self.rolling_wpms:
            avg_wpm = statistics.mean(self.rolling_wpms)
            wpm_stdev = statistics.stdev(self.rolling_wpms) if len(self.rolling_wpms) > 1 else 5
        elif self.word_wpms:
            avg_wpm = statistics.mean(self.word_wpms)
            wpm_stdev = statistics.stdev(self.word_wpms) if len(self.word_wpms) > 1 else 5
        else:
            avg_wpm = (total_chars / 5) / (total_duration / 60)
            wpm_stdev = 5

        # --- Error rate ---
        # Approximate: each correction = at least 1 error
        total_words = total_chars / 5
        error_rate = len(self.corrections) / max(total_chars, 1)

        # --- Correction delay (chars typed before noticing) ---
        correction_delays = [c.chars_deleted for c in self.corrections]
        correction_delay_min = min(correction_delays) if correction_delays else 0
        correction_delay_max = max(correction_delays) if correction_delays else 3
        correction_delay_median = (
            statistics.median(correction_delays) if correction_delays else 1
        )

        # --- Pause analysis ---
        sentence_pauses = [p.duration for p in self.pauses if p.context == "sentence"]
        paragraph_pauses = [p.duration for p in self.pauses if p.context == "paragraph"]
        thinking_pauses = [
            p.duration for p in self.pauses
            if p.context in ("word_boundary", "mid_word")
        ]
        pause_frequency = len(thinking_pauses) / max(total_chars, 1)

        # --- Burst analysis ---
        burst_enabled = len(self.burst_lengths) > 3
        if burst_enabled:
            burst_len_min = int(statistics.quantiles(self.burst_lengths, n=4)[0])
            burst_len_max = int(statistics.quantiles(self.burst_lengths, n=4)[2])
            median_interval = statistics.median(self.intervals)
            median_cps = 1.0 / median_interval if median_interval > 0 else 10
            avg_burst_cps = statistics.mean(self.burst_speeds) if self.burst_speeds else median_cps
            burst_multiplier = avg_burst_cps / median_cps if median_cps > 0 else 1.2
            burst_multiplier = max(1.05, min(burst_multiplier, 2.0))
        else:
            burst_len_min = 5
            burst_len_max = 15
            burst_multiplier = 1.15

        # --- Fatigue (WPM trend over session) ---
        fatigue_detected = False
        fatigue_rate = 0.0015
        if len(self.rolling_wpms) >= 6:
            first_third = self.rolling_wpms[:len(self.rolling_wpms) // 3]
            last_third = self.rolling_wpms[-(len(self.rolling_wpms) // 3):]
            if first_third and last_third:
                first_avg = statistics.mean(first_third)
                last_avg = statistics.mean(last_third)
                if first_avg > 0:
                    slowdown = (first_avg - last_avg) / first_avg
                    if slowdown > 0.03:
                        fatigue_detected = True
                        fatigue_rate = slowdown / max(total_duration, 1) * 10

        # --- Per-char-class timing multipliers ---
        char_class_multipliers = {}
        if self.intervals:
            base_median = statistics.median(self.intervals)
            for cls, times in self.char_intervals.items():
                if len(times) >= 3 and base_median > 0:
                    cls_median = statistics.median(times)
                    char_class_multipliers[cls] = round(cls_median / base_median, 3)

        # --- Digraph timing (top fastest and slowest) ---
        digraph_stats = {}
        if self.intervals:
            base_median = statistics.median(self.intervals)
            for dg, times in self.digraph_intervals.items():
                if len(times) >= 3 and base_median > 0:
                    dg_median = statistics.median(times)
                    digraph_stats[dg] = round(dg_median / base_median, 3)

        fast_digraphs = sorted(
            [(dg, r) for dg, r in digraph_stats.items() if r < 0.92],
            key=lambda x: x[1],
        )[:20]
        slow_digraphs = sorted(
            [(dg, r) for dg, r in digraph_stats.items() if r > 1.10],
            key=lambda x: -x[1],
        )[:20]

        # --- Backspace speed ---
        all_bs_intervals = []
        for c in self.corrections:
            all_bs_intervals.extend(c.backspace_intervals)
        avg_bs_interval = (
            statistics.mean(all_bs_intervals) if all_bs_intervals else 0.08
        )

        # --- Correction pause times ---
        correction_pause_before = [c.pause_before for c in self.corrections if c.pause_before < 5]
        correction_pause_after = [c.pause_after for c in self.corrections if c.pause_after < 5]

        thinking_min = min(thinking_pauses) if thinking_pauses else 0.3
        thinking_max = (statistics.quantiles(thinking_pauses, n=4)[2]
                        if len(thinking_pauses) >= 4 else 4.0)
        thinking_max = max(thinking_min, thinking_max)

        # --- Build settings (Ghost Typer compatible) ---
        settings = {
            "wpm": int(round(avg_wpm)),
            "wpm_variance": int(round(min(wpm_stdev * 2, avg_wpm * 0.4))),
            "error_rate": round(min(error_rate, 0.25), 4),
            "correction_delay_chars_min": min(12, max(0, correction_delay_min)),
            "correction_delay_chars_max": min(correction_delay_max, 12),
            "pause_frequency": round(min(pause_frequency, 0.3), 4),
            "pause_duration_min": round(thinking_min, 2),
            "pause_duration_max": round(thinking_max, 2),
            "fatigue_enabled": fatigue_detected,
            "fatigue_rate": round(fatigue_rate, 5),
            "burst_typing_enabled": burst_enabled,
            "burst_length_min": max(3, burst_len_min),
            "burst_length_max": max(burst_len_max, burst_len_min + 3),
            "burst_speed_multiplier": round(burst_multiplier, 3),
            "sentence_pause_min": round(
                min(sentence_pauses) if sentence_pauses else 0.8, 2
            ),
            "sentence_pause_max": round(
                max(sentence_pauses) if sentence_pauses else 2.5, 2
            ),
            "paragraph_pause_min": round(
                min(paragraph_pauses) if paragraph_pauses else 2.5, 2
            ),
            "paragraph_pause_max": round(
                max(paragraph_pauses) if paragraph_pauses else 7.0, 2
            ),
        }

        # --- Build full profile (settings + detailed analysis) ---
        profile = {
            "ghost_typer_settings": settings,
            "analysis": {
                "session_duration_sec": round(total_duration, 1),
                "total_keystrokes": len(self.events),
                "total_chars_typed": total_chars,
                "total_corrections": len(self.corrections),
                "avg_wpm": round(avg_wpm, 1),
                "wpm_stdev": round(wpm_stdev, 1),
                "median_interval_ms": round(
                    statistics.median(self.intervals) * 1000, 1
                ) if self.intervals else 0,
                "error_rate_pct": round(error_rate * 100, 2),
                "correction_delay_median": round(correction_delay_median, 1),
                "avg_backspace_interval_ms": round(avg_bs_interval * 1000, 1),
                "correction_pause_before_ms": round(
                    statistics.mean(correction_pause_before) * 1000, 1
                ) if correction_pause_before else 0,
                "correction_pause_after_ms": round(
                    statistics.mean(correction_pause_after) * 1000, 1
                ) if correction_pause_after else 0,
                "fatigue_detected": fatigue_detected,
                "burst_count": len(self.burst_lengths),
                "avg_burst_length": round(
                    statistics.mean(self.burst_lengths), 1
                ) if self.burst_lengths else 0,
                "thinking_pause_count": len(thinking_pauses),
                "sentence_pause_count": len(sentence_pauses),
                "paragraph_pause_count": len(paragraph_pauses),
                "char_class_multipliers": char_class_multipliers,
                "fast_digraphs": dict(fast_digraphs),
                "slow_digraphs": dict(slow_digraphs),
                "rolling_wpm_curve": [round(w, 1) for w in self.rolling_wpms],
            },
        }

        return profile


def _char_class(char: str) -> str:
    """Classify a character for timing analysis."""
    if not char or len(char) != 1:
        return "other"
    if char.isalpha():
        if char.isupper():
            return "uppercase"
        return "lowercase"
    if char.isdigit():
        return "digit"
    if char == " ":
        return "space"
    if char == "\n":
        return "enter"
    if char in ".,;:":
        return "common_punct"
    return "symbol"


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_profile(profile: dict) -> None:
    """Print a human-readable summary of the typing profile."""
    settings = profile["ghost_typer_settings"]
    analysis = profile["analysis"]

    print("\n" + "=" * 60)
    print("  TYPING PROFILE ANALYSIS")
    print("=" * 60)

    print(f"\n  Session: {analysis['session_duration_sec']:.0f}s, "
          f"{analysis['total_keystrokes']} keystrokes, "
          f"{analysis['total_chars_typed']} characters")

    print(f"\n  SPEED")
    print(f"    Average WPM:       {analysis['avg_wpm']:.0f}")
    print(f"    WPM std dev:       {analysis['wpm_stdev']:.1f}")
    print(f"    Median interval:   {analysis['median_interval_ms']:.0f}ms")

    # WPM sparkline
    if analysis["rolling_wpm_curve"]:
        curve = analysis["rolling_wpm_curve"]
        lo, hi = min(curve), max(curve)
        blocks = " _.-~*"
        sparkline = ""
        for w in curve:
            idx = int((w - lo) / max(hi - lo, 1) * (len(blocks) - 1))
            sparkline += blocks[idx]
        print(f"    WPM over time:     [{sparkline}]  ({lo:.0f}-{hi:.0f})")

    print(f"\n  ERRORS")
    print(f"    Error rate:        {analysis['error_rate_pct']:.1f}%")
    print(f"    Corrections:       {analysis['total_corrections']}")
    print(f"    Avg chars deleted:  {analysis['correction_delay_median']:.0f}")
    print(f"    Pause before fix:  {analysis['correction_pause_before_ms']:.0f}ms")
    print(f"    Backspace speed:   {analysis['avg_backspace_interval_ms']:.0f}ms/key")

    print(f"\n  PAUSES")
    print(f"    Thinking pauses:   {analysis['thinking_pause_count']}")
    print(f"    Sentence pauses:   {analysis['sentence_pause_count']}")
    print(f"    Paragraph pauses:  {analysis['paragraph_pause_count']}")

    print(f"\n  BURSTS")
    print(f"    Burst count:       {analysis['burst_count']}")
    if analysis["avg_burst_length"]:
        print(f"    Avg burst length:  {analysis['avg_burst_length']:.0f} chars")
    print(f"    Burst speed mult:  {settings['burst_speed_multiplier']:.2f}x")

    print(f"\n  FATIGUE")
    print(f"    Detected:          {'Yes' if analysis['fatigue_detected'] else 'No'}")

    if analysis["char_class_multipliers"]:
        print(f"\n  CHAR CLASS SPEED (relative to median)")
        for cls, mult in sorted(analysis["char_class_multipliers"].items(), key=lambda x: x[1]):
            bar_len = int(mult * 20)
            bar = "#" * bar_len
            label = "fast" if mult < 0.9 else "slow" if mult > 1.1 else ""
            print(f"    {cls:<14s} {mult:.2f}x  {bar}  {label}")

    if analysis["fast_digraphs"]:
        pairs = ", ".join(f"{dg}({r:.2f})" for dg, r in list(analysis["fast_digraphs"].items())[:10])
        print(f"\n  FAST DIGRAPHS: {pairs}")

    if analysis["slow_digraphs"]:
        pairs = ", ".join(f"{dg}({r:.2f})" for dg, r in list(analysis["slow_digraphs"].items())[:10])
        print(f"  SLOW DIGRAPHS: {pairs}")

    print(f"\n  GHOST TYPER SETTINGS")
    for key, val in settings.items():
        print(f"    {key}: {val}")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SAMPLE_PROMPTS = [
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.",
    "She sells seashells by the seashore. The shells she sells are surely seashells.",
    "How vexingly quick daft zebras jump! The five boxing wizards jump quickly.",
    "A journey of a thousand miles begins with a single step. Knowledge is power.",
    "To be or not to be, that is the question. Whether it is nobler in the mind to suffer.",
]

LONG_PROMPT = """The Industrial Revolution, which began in Britain in the late 18th century, fundamentally transformed how people lived and worked. Before this period, most goods were produced by hand in small workshops or homes. The introduction of machinery, powered first by water and then by steam, allowed factories to produce goods on a massive scale.

This shift had profound effects on society. People moved from rural areas to cities in search of factory jobs, leading to rapid urbanization. Working conditions in early factories were often harsh, with long hours, low pay, and dangerous machinery. Children as young as five were employed in mines and mills.

However, the Industrial Revolution also brought significant improvements over time. New technologies made goods cheaper and more accessible. Transportation networks expanded with railways and steamships. Communication improved with the telegraph and later the telephone. These advances laid the groundwork for the modern world we live in today.

Despite its benefits, industrialization created new challenges that societies continue to grapple with, including environmental pollution, economic inequality, and the displacement of workers by machines. Understanding this history helps us navigate similar transitions happening today with artificial intelligence and automation."""


def main():
    parser = argparse.ArgumentParser(description="Ghost Typer — Typing Profiler")
    parser.add_argument("--prompt", type=str, help="Path to a text file to use as typing prompt")
    parser.add_argument("--output", "-o", type=str, default="typing_profile.json",
                        help="Output file path (default: typing_profile.json)")
    parser.add_argument("--freeform", action="store_true",
                        help="Skip the prompt, just type freely")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  GHOST TYPER — TYPING PROFILER")
    print("=" * 60)
    print()

    if args.prompt:
        prompt_text = Path(args.prompt).read_text()
    elif not args.freeform:
        prompt_text = LONG_PROMPT
    else:
        prompt_text = None

    if prompt_text:
        print("  Type the following text as naturally as you can.")
        print("  Don't worry about mistakes — just type like you normally do.")
        print("  Press ESC when you're done.\n")
        print("  ----")
        for line in prompt_text.strip().split("\n"):
            print(f"  {line}")
        print("  ----\n")
    else:
        print("  FREEFORM MODE: Type whatever you want, as naturally as possible.")
        print("  Type for at least 1-2 minutes for good results.")
        print("  Press ESC when you're done.\n")

    print("  Start typing now...\n")
    print("-" * 60)

    recorder = TypingRecorder()
    recorder.start()

    # Wait for ESC
    try:
        while not recorder.is_done:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()

    print("\n" + "-" * 60)
    print(f"\n  Recorded {len(recorder.events)} keystrokes. Analyzing...\n")

    if len(recorder.events) < 20:
        print("  Not enough data. Type more next time (at least 20 keystrokes).")
        sys.exit(1)

    analyzer = TypingAnalyzer(recorder.events)
    profile = analyzer.analyze()

    # Print results
    print_profile(profile)

    # Save
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"\n  Profile saved to: {output_path.resolve()}")

    # Also save just the settings for direct use with Ghost Typer
    settings_path = output_path.with_suffix(".settings.json")
    with open(settings_path, "w") as f:
        json.dump(profile["ghost_typer_settings"], f, indent=2)
    print(f"  Settings saved to: {settings_path.resolve()}")
    print(f"\n  To use: copy {settings_path.name} values into Ghost Typer settings.\n")


if __name__ == "__main__":
    main()
