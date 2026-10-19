"""Typing planner — converts formatted text segments into a TypingPlan.

Knows Google Docs keyboard shortcuts and builds a realistic sequence
of TypingActions, pre-planning mistakes, pauses, and rewrites.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from .models import (
    AbandonWord,
    ApplyFormatting,
    DistractionPause,
    FormatType,
    MakeMistake,
    Pause,
    PressKey,
    Rewrite,
    Settings,
    TextSegment,
    TypeText,
    TypingAction,
    TypingPlan,
    TypingProfile,
)
from .human_errors import HumanErrors
from .typing_engine import TypingEngine
from .planned_text import PlannedText, replace_known_span

_WORD_RE = re.compile(r"\w+")

# Google Docs keyboard shortcuts (macOS)
FORMAT_SHORTCUTS: dict[str, tuple[str, ...]] = {
    "bold": ("cmd", "b"),
    "italic": ("cmd", "i"),
    "underline": ("cmd", "u"),
    "heading_1": ("cmd", "opt", "1"),
    "heading_2": ("cmd", "opt", "2"),
    "heading_3": ("cmd", "opt", "3"),
    "heading_4": ("cmd", "opt", "4"),
    "heading_5": ("cmd", "opt", "5"),
    "heading_6": ("cmd", "opt", "6"),
    "numbered_list": ("cmd", "shift", "7"),
    "bulleted_list": ("cmd", "shift", "8"),
    "align_left": ("cmd", "shift", "l"),
    "align_center": ("cmd", "shift", "e"),
    "align_right": ("cmd", "shift", "r"),
    "align_justify": ("cmd", "shift", "j"),
}

FORMAT_TYPE_MAP: dict[str, FormatType] = {
    "bold": FormatType.BOLD,
    "italic": FormatType.ITALIC,
    "underline": FormatType.UNDERLINE,
    "heading_1": FormatType.HEADING_1,
    "heading_2": FormatType.HEADING_2,
    "heading_3": FormatType.HEADING_3,
    "heading_4": FormatType.HEADING_4,
    "heading_5": FormatType.HEADING_5,
    "heading_6": FormatType.HEADING_6,
    "numbered_list": FormatType.NUMBERED_LIST,
    "bulleted_list": FormatType.BULLETED_LIST,
    "align_left": FormatType.ALIGN_LEFT,
    "align_center": FormatType.ALIGN_CENTER,
    "align_right": FormatType.ALIGN_RIGHT,
    "align_justify": FormatType.ALIGN_JUSTIFY,
}

# Regex to split text into sentences (keep the trailing space with the preceding sentence)
SENTENCE_RE = re.compile(r"(?<=[.!?]\s)(?=\S)")

# Regex to split into phrases (keep delimiter and trailing space with the preceding phrase)
PHRASE_RE = re.compile(r"(?<=[,;:\u2014\u2013]\s)(?=\S)")


@dataclass
class _Chunk:
    """Internal: a small piece of text that will become one or more TypingActions."""

    text: str
    is_paragraph_end: bool = False
    is_sentence_end: bool = False
    is_thought_boundary: bool = False  # new idea/topic starts here


# Thought boundary positions are detected by AI (see _detect_thought_boundaries).
# No hardcoded word lists.


def validate_behavioral_content(data: object, text: str) -> dict:
    """Sanitize optional AI annotations before any planner branch consumes them."""
    if not isinstance(data, dict):
        return {}
    result = {}
    for key in ("word_abandonments", "sentence_restructures", "distraction_points",
                "quote_ranges", "autocorrect_fixes", "proofreading_fixes",
                "word_speed_map", "word_difficulty_ratings", "syllable_boundaries",
                "composition_annotations"):
        entries = data.get(key, [])
        if not isinstance(entries, list):
            continue
        valid = []
        for entry in entries[:100]:
            if not isinstance(entry, dict):
                continue
            def string(name, limit=500):
                value = entry.get(name)
                # These are inline words/phrases and temporary drafts. Control
                # characters can navigate the destination (Tab/Return) and make
                # the subsequent deletion or cursor moves target another field.
                return (isinstance(value, str) and 0 < len(value) <= limit
                        and value.isprintable())
            def number(name, low, high, integer=False):
                value = entry.get(name)
                return (isinstance(value, (int, float)) and not isinstance(value, bool)
                        and low <= value <= high and math.isfinite(value)
                        and (not integer or isinstance(value, int)))
            if key == "word_speed_map":
                okay = string("word", 100) and number("multiplier", .1, 10)
            elif key == "word_difficulty_ratings":
                okay = string("word", 100) and number("difficulty", 0, 1)
            elif key == "syllable_boundaries":
                syllables = entry.get("syllables")
                okay = (string("word", 100) and isinstance(syllables, list)
                        and 1 < len(syllables) <= 30
                        and all(isinstance(s, str) and s for s in syllables)
                        and "".join(syllables).lower() == entry["word"].lower())
            elif key in ("quote_ranges", "composition_annotations"):
                okay = (number("start", 0, len(text), True)
                        and number("end", 0, len(text), True)
                        and entry["start"] < entry["end"])
                if key == "quote_ranges":
                    okay = okay and entry.get("type", "direct_quote") in ("direct_quote", "block_quote", "paraphrase_close")
                else:
                    okay = okay and entry.get("mode") in ("copy", "composition")
            elif key == "word_abandonments":
                okay = (string("word", 100) and string("replacement", 100)
                        and entry["word"].isascii()
                        and number("abandon_after_chars", 1, len(entry["word"]) - 1, True))
            elif key == "sentence_restructures":
                okay = (string("original_sentence", 2000) and string("first_draft", 4000)
                        and entry["first_draft"].isascii()
                        and entry["original_sentence"] in text
                        and len(entry["first_draft"]) <= max(100, 2 * len(entry["original_sentence"])))
            elif key == "distraction_points":
                okay = (number("position", 0, len(text), True)
                        and entry.get("quality", "low") in ("high", "medium", "low"))
            elif key == "autocorrect_fixes":
                okay = string("word", 100) and string("correct", 100)
            else:
                okay = string("original") and string("fixed")
            if okay:
                valid.append(entry)
        if valid:
            result[key] = valid
    return result


class PlanningCancelled(RuntimeError):
    """The session was stopped before its plan could be completed."""


class TypingPlanner:
    """Converts TextSegments into a TypingPlan with realistic mistakes and pauses."""

    # Includes repeats and nested rewrites. Exhaustion falls back to local typing.
    MAX_DRAFT_REQUESTS_PER_PLAN = 8
    MAX_REVISIT_REQUESTS_PER_PLAN = 5

    def __init__(self, settings: Settings | None = None, ai_rewriter=None, profile: TypingProfile | None = None, *, ai_enabled: bool = True, api_key: str | None = None) -> None:
        self.settings = settings or Settings()
        self._profile = profile or TypingProfile.defaults()
        self.engine = TypingEngine(self.settings, profile=self._profile)
        self._rng = random.Random()
        self._ai_rewriter = ai_rewriter  # AIRewriter instance (optional)
        self._draft_cache: dict[str, str | None] = {}  # final_text -> draft_text
        self._draft_requests = 0
        self._thought_boundaries: set[int] = set()  # char positions of thought boundaries
        self._human_errors = HumanErrors(
            enabled=ai_enabled, api_key=api_key,
            misspelling_rate=self.settings.error_rate,
            grammar_error_rate=getattr(self.settings, 'grammar_error_rate', 0.15),
            punctuation_error_rate=getattr(self.settings, 'punctuation_error_rate', 0.2),
        )
        # Behavioral content defaults (set properly in plan())
        self._behavioral_content: dict = {}
        self._abandon_count = 0
        self._restructure_count = 0
        self._autocorrect_count = 0
        self._autocorrect_attempts = 0
        self._distraction_count = 0
        self._chars_since_distraction = 0
        self._word_speed_cache: dict[str, float] | None = None
        self._pending_autocorrects: list[dict] = []
        self._char_position = 0
        self._typed_prefix = ""
        self._chunk_prefix = ""
        self._cancelled = lambda: False

    def _check_cancelled(self) -> None:
        if self._cancelled():
            raise PlanningCancelled("Typing planning cancelled")

    @property
    def profile(self) -> TypingProfile:
        return self._profile

    @profile.setter
    def profile(self, value: TypingProfile) -> None:
        self._profile = value
        self.engine.profile = value

    def seed(self, value: int) -> None:
        self._rng.seed(value)
        self.engine.seed(value)

    def _r(self, r) -> float:
        """Sample a random float from a Range."""
        return self._rng.uniform(r.min, r.max)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(self, segments: list[TextSegment], simple: bool = False, behavioral_content: dict | None = None, *, cancelled=None) -> TypingPlan:
        """Build a complete TypingPlan from a list of TextSegments.

        Args:
            simple: If True, use simplified planning — no proofreading, no
                    rewrites, no arrow keys. Safe for table cells where arrow
                    keys would escape the cell.
            behavioral_content: AI-generated behavioral data (word speeds,
                    abandonments, distractions, etc.). Empty dict = no-op.
        """
        self._cancelled = cancelled or (lambda: False)
        self._check_cancelled()
        # pynput treats both CR and LF as Enter; one CRLF must be one event.
        if any("\r" in segment.text for segment in segments):
            segments = [replace(segment, text=segment.text.replace("\r\n", "\n").replace("\r", "\n")) for segment in segments]

        actions: list[TypingAction] = []
        total_chars = 0
        total_paste_chars = sum(len(seg.text) for seg in segments)

        # Store behavioral content for use by sub-methods
        self._behavioral_content = validate_behavioral_content(
            behavioral_content, "".join(seg.text for seg in segments))

        # Request drafts only for spans that are actually selected. A hard
        # session budget also covers repeated, cascading, and failed requests.
        self._draft_cache.clear()
        self._draft_requests = 0

        self._human_errors.reset_budget()

        # Detect thought boundaries via AI
        if not simple:
            full_text = "".join(seg.text for seg in segments)
            self._check_cancelled()
            self._thought_boundaries = set(
                self._human_errors.find_thought_boundaries(full_text)
            )
            self._check_cancelled()

        # Reset revisit counter for this planning session
        self._revisit_count = 0
        self._revisit_requests = 0

        # Reset new-feature counters for this planning session
        self._abandon_count = 0
        self._restructure_count = 0
        self._autocorrect_count = 0
        self._autocorrect_attempts = 0
        self._distraction_count = 0
        self._chars_since_distraction = 0
        self._word_speed_cache: dict[str, float] | None = None
        self._pending_autocorrects: list[dict] = []  # autocorrect fixes waiting to be applied
        self._char_position = 0  # cumulative char position across all segments

        # Track cumulative text typed so far (for revisit targeting)
        typed_so_far = ""
        navigation_valid = True

        for seg_idx, segment in enumerate(segments):
            self._check_cancelled()
            self._typed_prefix = typed_so_far
            if simple:
                seg_actions, seg_chars = self._plan_segment_simple(segment)
            else:
                seg_actions, seg_chars = self._plan_segment(
                    segment, seg_idx, len(segments), total_paste_chars
                )
            actions.extend(seg_actions)
            total_chars += seg_chars
            state = PlannedText(typed_so_far).apply(seg_actions)
            navigation_valid = navigation_valid and state.valid
            typed_so_far = state.text

            # At paragraph boundaries, occasionally go back and revise earlier text
            if (
                not simple
                and navigation_valid
                and seg_idx > 0
                and seg_idx < len(segments) - 1
                and total_paste_chars > 300
            ):
                revisit_actions = self._maybe_build_revisit(
                    typed_so_far, total_paste_chars
                )
                if revisit_actions:
                    actions.extend(revisit_actions)
                    typed_so_far = PlannedText(typed_so_far).apply(revisit_actions).text

        # --- Final proofreading pass (Feature 13) ---
        if not simple:
            proofread_actions = self._build_final_proofread(typed_so_far) if navigation_valid else []
            if proofread_actions:
                actions.extend(proofread_actions)

        # Estimate duration (rough: based on WPM)
        chars_per_sec = (self.settings.wpm * 5) / 60
        est_duration = total_chars / chars_per_sec if chars_per_sec > 0 else 0

        return TypingPlan(
            actions=actions,
            total_characters=total_chars,
            estimated_duration_seconds=est_duration,
            segment_count=len(segments),
        )

    # ------------------------------------------------------------------
    # Segment-level planning
    # ------------------------------------------------------------------

    def _plan_segment(
        self, segment: TextSegment, seg_idx: int, total_segments: int,
        total_paste_chars: int = 500,
    ) -> tuple[list[TypingAction], int]:
        """Plan actions for a single TextSegment. Returns (actions, char_count)."""
        actions: list[TypingAction] = []
        char_count = 0

        # Structural break segments must bypass sentence chunking, which
        # intentionally ignores whitespace-only input.
        if segment.text and not segment.text.strip() and "\n" in segment.text:
            for char in segment.text:
                actions.append(PressKey(key="enter") if char == "\n" else TypeText(text=char))
            self._char_position += len(segment.text)
            return actions, len(segment.text)

        # --- Skip all formatting — type as plain text so it inherits destination style ---

        # --- Apply human errors (grammar, punctuation, spelling that stay in) ---
        if self.settings.grammar_error_rate > 0 or self.settings.punctuation_error_rate > 0:
            self._check_cancelled()
            modified_text, misspellings = self._human_errors.process_text(segment.text)
            self._check_cancelled()
            self._remap_source_annotations(segment.text, modified_text, self._char_position)
            # Preserve the validated occurrence, rather than redirecting a typo
            # to the first case-insensitive match elsewhere in the paragraph.
            misspell_by_position = {pos: (wrong, correct) for wrong, correct, pos in misspellings}
        else:
            modified_text = segment.text
            misspell_by_position = {}

        # --- Break text into typeable chunks ---
        chunks = self._break_into_chunks(modified_text, text_offset=self._char_position)

        sentences_since_thought_pause = 0
        # Every 2-4 sentences without a thought boundary, insert a thought pause
        next_thought_pause_at = self._rng.randint(self.profile.pauses.thought_pause_sentences_interval.min, self.profile.pauses.thought_pause_sentences_interval.max)
        emitted = PlannedText(self._typed_prefix, track_typos=True,
                              max_typo_distance=self.profile.proofread.max_proofread_distance)
        applied_actions = 0

        segment_offset = 0
        for chunk in chunks:
            chunk_misspellings = {pos - segment_offset: pair
                                  for pos, pair in misspell_by_position.items()
                                  if segment_offset <= pos < segment_offset + len(chunk.text)}
            segment_offset += len(chunk.text)
            # Track sentences and inject periodic thought pauses
            if chunk.is_thought_boundary:
                sentences_since_thought_pause = 0
                next_thought_pause_at = self._rng.randint(self.profile.pauses.thought_pause_sentences_interval.min, self.profile.pauses.thought_pause_sentences_interval.max)
            elif chunk.is_sentence_end or chunk.is_paragraph_end:
                sentences_since_thought_pause += 1
                if sentences_since_thought_pause >= next_thought_pause_at:
                    duration = self._r(self.profile.pauses.thought_pause_duration)
                    actions.append(Pause(duration=duration, description="Pausing to collect thoughts"))
                    sentences_since_thought_pause = 0
                    next_thought_pause_at = self._rng.randint(self.profile.pauses.thought_pause_sentences_interval.min, self.profile.pauses.thought_pause_sentences_interval.max)

            # --- Sentence restructuring (Feature 6) ---
            restructured = False
            if self._should_restructure(chunk.text):
                restructure_entry = self._find_restructure_match(chunk.text)
                if (restructure_entry and self._rng.random()
                        < self.profile.behaviors.restructuring.probability_per_sentence):
                    first_draft = restructure_entry["first_draft"]
                    # Type the first draft
                    actions.append(TypeText(text=first_draft))
                    # Pause for thinking
                    actions.append(Pause(
                        duration=self._r(self.profile.behaviors.restructuring.thinking_pause),
                        description="Reconsidering sentence structure",
                    ))
                    # Rewrite: delete the draft, type the real text
                    actions.append(Rewrite(
                        delete_count=len(first_draft),
                        new_actions=[TypeText(text=chunk.text)],
                        description="Restructuring sentence",
                    ))
                    char_count += len(chunk.text)
                    self._restructure_count += 1
                    self._char_position += len(chunk.text)
                    self._chars_since_distraction += len(chunk.text)
                    restructured = True

            if not restructured:
                self._chunk_prefix = emitted.text
                chunk_actions, chunk_chars, chunk_typos = self._plan_chunk(
                    chunk, misspell_by_position=chunk_misspellings, total_paste_chars=total_paste_chars
                )
                actions.extend(chunk_actions)
                char_count += chunk_chars
                self._chars_since_distraction += chunk_chars

            # Replay only the new actions, rather than the entire paragraph
            # prefix on every chunk (quadratic for large pastes).
            emitted.apply(actions[applied_actions:])
            applied_actions = len(actions)

            # Proofread at sentence/paragraph boundaries — only if there are real typos to fix
            if (chunk.is_sentence_end or chunk.is_paragraph_end) and emitted.typos:
                if self._rng.random() < self.settings.proofread_probability:
                    proof_actions = self._build_proofread(
                        emitted.typos, len(emitted.text),
                        known_text=emitted.text if emitted.valid else "",
                    )
                    actions.extend(proof_actions)

            # --- Distraction pauses (Feature 7) ---
            if chunk.is_sentence_end or chunk.is_paragraph_end:
                distraction = self._maybe_insert_distraction(self._char_position)
                if distraction:
                    actions.append(distraction)

            emitted.apply(actions[applied_actions:])
            applied_actions = len(actions)

        # --- No formatting to untoggle (plain text mode) ---

        return actions, char_count

    def _remap_source_annotations(self, original: str, modified: str, start: int) -> None:
        """Keep source annotations aligned when sparse grammar edits change length.

        Offsets beyond this segment shift together. A boundary inside replaced
        text has no reliable target and is discarded instead of moving a quote
        or thinking pause onto an unrelated word.
        """
        if original == modified:
            return
        prefix = 0
        limit = min(len(original), len(modified))
        while prefix < limit and original[prefix] == modified[prefix]:
            prefix += 1
        suffix = 0
        while (suffix < limit - prefix
               and original[-suffix - 1] == modified[-suffix - 1]):
            suffix += 1
        before = original[prefix:len(original) - suffix]
        after = modified[prefix:len(modified) - suffix]
        # SequenceMatcher can take quadratic time on repetitive changes. Losing
        # optional positional effects is preferable to blocking a large paste.
        if len(before) * len(after) > 1_000_000:
            for key in ("quote_ranges", "composition_annotations"):
                if key in self._behavioral_content:
                    self._behavioral_content[key] = [e for e in self._behavioral_content[key] if e["end"] <= start]
            if "distraction_points" in self._behavioral_content:
                self._behavioral_content["distraction_points"] = [e for e in self._behavioral_content["distraction_points"] if e["position"] < start]
            self._thought_boundaries = {p for p in self._thought_boundaries if p < start}
            return
        blocks = [(0, 0, prefix),
                  *((a + prefix, b + prefix, size) for a, b, size in
                    SequenceMatcher(None, before, after, autojunk=True).get_matching_blocks() if size),
                  (len(original) - suffix, len(modified) - suffix, suffix)]
        delta = len(modified) - len(original)

        def remap(position, *, end=False):
            local = position - start
            if local < 0:
                return position
            if local >= len(original):
                return position + delta
            for old_start, new_start, size in blocks:
                inside = (old_start < local <= old_start + size) if end else (old_start <= local < old_start + size)
                if inside:
                    return start + new_start + local - old_start
            return None

        for key in ("quote_ranges", "composition_annotations"):
            mapped = []
            for entry in self._behavioral_content.get(key, []):
                lo, hi = remap(entry["start"]), remap(entry["end"], end=True)
                if lo is not None and hi is not None and lo < hi:
                    mapped.append({**entry, "start": lo, "end": hi})
            if key in self._behavioral_content:
                self._behavioral_content[key] = mapped
        if "distraction_points" in self._behavioral_content:
            self._behavioral_content["distraction_points"] = [
                {**entry, "position": position}
                for entry in self._behavioral_content["distraction_points"]
                if (position := remap(entry["position"])) is not None]
        self._thought_boundaries = {position for boundary in self._thought_boundaries
                                    if (position := remap(boundary)) is not None}

    def _plan_segment_simple(self, segment: TextSegment) -> tuple[list[TypingAction], int]:
        """Simple planning: just type the text with realistic timing and basic typos.

        No proofreading, no rewrites, no arrow keys — safe for table cells.
        """
        actions: list[TypingAction] = []
        text = segment.text
        if not text:
            return actions, 0

        char_count = 0
        i = 0
        while i < len(text):
            self._check_cancelled()
            char = text[i]

            # Occasional single-char mistake (backspace and fix, no arrow keys)
            if char.isascii() and char.isalpha() and self._rng.random() < self.settings.error_rate:
                typo_char = self.engine.generate_typo(char)
                if (typo_char and typo_char != char and len(typo_char) == 1
                        and typo_char.isascii() and typo_char.isprintable()):
                    # Type wrong char, backspace, type correct
                    actions.append(TypeText(text=typo_char))
                    actions.append(Rewrite.simple(delete_count=1, text=char))
                    char_count += 1
                    i += 1
                    continue

            # Normal typing — accumulate a run
            run_start = i
            # A dropped/double/unchanged typo is unsuitable in simple mode.
            # Consume its source character normally instead of rerolling the
            # same position forever when the configured error rate is 100%.
            i += 1
            while i < len(text) and not (text[i].isascii() and text[i].isalpha() and self._rng.random() < self.settings.error_rate):
                i += 1
                if i - run_start > 8:  # break runs to keep them natural
                    break
            run_text = text[run_start:i]
            if run_text:
                actions.append(TypeText(text=run_text))
                char_count += len(run_text)

        self._char_position += len(text)
        return actions, char_count

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _formatting_actions_for(self, segment: TextSegment) -> list[TypingAction]:
        """Determine which formatting shortcuts to press before typing."""
        actions: list[TypingAction] = []
        fmt = segment.formatting

        # Heading level
        heading = fmt.get("heading_level", 0)
        if heading and 1 <= heading <= 6:
            key = f"heading_{heading}"
            self._maybe_add_formatting_hesitation(actions, key)
            actions.append(ApplyFormatting(
                format_type=FORMAT_TYPE_MAP[key],
                shortcut=FORMAT_SHORTCUTS[key],
            ))

        # List type
        list_type = fmt.get("list_type")
        if list_type in ("numbered", "numbered_list"):
            self._maybe_add_formatting_hesitation(actions, "numbered_list")
            actions.append(ApplyFormatting(
                format_type=FormatType.NUMBERED_LIST,
                shortcut=FORMAT_SHORTCUTS["numbered_list"],
            ))
        elif list_type in ("bulleted", "bulleted_list", "bullet"):
            self._maybe_add_formatting_hesitation(actions, "bulleted_list")
            actions.append(ApplyFormatting(
                format_type=FormatType.BULLETED_LIST,
                shortcut=FORMAT_SHORTCUTS["bulleted_list"],
            ))

        # Alignment
        alignment = fmt.get("alignment")
        if alignment:
            align_key = f"align_{alignment}"
            if align_key in FORMAT_SHORTCUTS:
                self._maybe_add_formatting_hesitation(actions, align_key)
                actions.append(ApplyFormatting(
                    format_type=FORMAT_TYPE_MAP[align_key],
                    shortcut=FORMAT_SHORTCUTS[align_key],
                ))

        # Bold / italic / underline (toggle ON)
        if fmt.get("bold"):
            self._maybe_add_formatting_hesitation(actions, "bold")
            actions.append(ApplyFormatting(
                format_type=FormatType.BOLD,
                shortcut=FORMAT_SHORTCUTS["bold"],
            ))
        if fmt.get("italic"):
            self._maybe_add_formatting_hesitation(actions, "italic")
            actions.append(ApplyFormatting(
                format_type=FormatType.ITALIC,
                shortcut=FORMAT_SHORTCUTS["italic"],
            ))
        if fmt.get("underline"):
            self._maybe_add_formatting_hesitation(actions, "underline")
            actions.append(ApplyFormatting(
                format_type=FormatType.UNDERLINE,
                shortcut=FORMAT_SHORTCUTS["underline"],
            ))

        return actions

    def _untoggle_formatting(self, segment: TextSegment) -> list[TypingAction]:
        """Turn off toggle-style formatting after the segment is typed."""
        actions: list[TypingAction] = []
        fmt = segment.formatting

        if fmt.get("bold"):
            actions.append(ApplyFormatting(
                format_type=FormatType.BOLD,
                shortcut=FORMAT_SHORTCUTS["bold"],
                description="Toggle off bold",
            ))
        if fmt.get("italic"):
            actions.append(ApplyFormatting(
                format_type=FormatType.ITALIC,
                shortcut=FORMAT_SHORTCUTS["italic"],
                description="Toggle off italic",
            ))
        if fmt.get("underline"):
            actions.append(ApplyFormatting(
                format_type=FormatType.UNDERLINE,
                shortcut=FORMAT_SHORTCUTS["underline"],
                description="Toggle off underline",
            ))

        return actions

    # ------------------------------------------------------------------
    # Text chunking
    # ------------------------------------------------------------------

    def _break_into_chunks(self, text: str, text_offset: int = 0) -> list[_Chunk]:
        """Split text into sentence / phrase / paragraph chunks."""
        chunks: list[_Chunk] = []

        # Split on paragraph boundaries (double newline or single newline)
        paragraphs = re.split(r"(\n+)", text)

        char_pos = 0  # track position within text for thought boundary lookup
        for p_idx, para in enumerate(paragraphs):
            if para and not para.strip() and "\n" in para:
                chunks.append(_Chunk(text=para, is_paragraph_end=True))
                char_pos += len(para)
                continue
            if not para:
                continue

            # Split paragraph into sentences
            sentences = SENTENCE_RE.split(para)

            for s_idx, sentence in enumerate(sentences):
                if not sentence:
                    continue

                is_last_sentence = s_idx == len(sentences) - 1

                # Detect thought boundary via AI-detected positions
                sentence_global_pos = text_offset + text.find(sentence, char_pos)
                starts_new_thought = sentence_global_pos in self._thought_boundaries

                # Further split long sentences into phrases
                phrases = self._split_into_phrases(sentence)

                for ph_idx, phrase in enumerate(phrases):
                    if not phrase:
                        continue
                    is_last_phrase = ph_idx == len(phrases) - 1
                    chunks.append(_Chunk(
                        text=phrase,
                        is_sentence_end=is_last_phrase and not is_last_sentence,
                        is_paragraph_end=is_last_phrase and is_last_sentence,
                        is_thought_boundary=starts_new_thought and ph_idx == 0,
                    ))

                char_pos = text.find(sentence, char_pos) + len(sentence)

        return chunks

    def _split_into_phrases(self, sentence: str) -> list[str]:
        """Split a sentence at phrase boundaries (commas, semicolons, etc.)."""
        parts = PHRASE_RE.split(sentence)
        result: list[str] = []
        for part in parts:
            if part.strip():
                result.append(part)
        return result if result else [sentence]

    # ------------------------------------------------------------------
    # Chunk-level planning (where mistakes and pauses are inserted)
    # ------------------------------------------------------------------

    def _plan_chunk(
        self, chunk: _Chunk, misspell_by_position: dict[int, tuple[str, str]] | None = None,
        total_paste_chars: int = 500,
    ) -> tuple[list[TypingAction], int, list[tuple[str, str, int]]]:
        """Plan actions for a single chunk of text.

        Returns (actions, char_count, uncorrected_typos).
        uncorrected_typos: list of (wrong_char, correct_char, chars_from_end)
        """
        actions: list[TypingAction] = []
        text = chunk.text
        char_count = 0
        misspell_by_position = misspell_by_position or {}
        # Track uncorrected typos: (wrong_char, correct_char, position_in_typed_output)
        uncorrected_typos: list[tuple[str, str, int]] = []

        # Thought boundary: long pause as the person gathers their next idea
        if chunk.is_thought_boundary:
            duration = self._rng.uniform(3.0, 8.0)
            actions.append(Pause(duration=duration, description="Gathering thoughts before new idea"))

        # Special case: newline
        if text and not text.strip() and "\n" in text:
            actions.extend(PressKey(key="enter") if char == "\n" else TypeText(text=char) for char in text)
            char_count += len(text)
            self._char_position += len(text)
            actions.append(Pause(duration=self.engine.paragraph_pause_duration()))
            return actions, char_count, []

        # Apply only the exact source occurrence and restore its original case.
        word_misspells: dict[int, tuple[str, str, int]] = {}
        for match in re.finditer(r"\b(\w+)\b", text):
            pair = misspell_by_position.get(match.start())
            if pair:
                wrong, correct = pair
                word = match.group(1)
                if word.lower() == correct.lower():
                    word_misspells[match.start()] = (wrong, word, len(word))

        # --- Pre-scan for single-char mistake positions (adjacent key misclicks) ---
        # Delayed corrections may backspace through following source text.
        # Native editors delete graphemes, so Unicode code-point counts cannot
        # safely identify the characters to remove. Keep natural typing timing.
        mistake_positions = self._pick_mistake_positions(text) if text.isascii() else set()
        rewrite_positions_list = self._pick_rewrite_positions(text, total_paste_chars)
        # Build a dict: pos -> granularity for quick lookup
        rewrite_positions: dict[int, str] = {pos: gran for pos, gran in rewrite_positions_list}
        abandonment_cfg = self.profile.behaviors.abandonment
        abandonment_words = ({entry["word"].lower()
                              for entry in self._behavioral_content.get("word_abandonments", [])}
                             if abandonment_cfg.enabled and abandonment_cfg.probability_per_word > 0
                             and self._abandon_count < abandonment_cfg.max_per_session else set())
        abandonment_positions = {match.start() for match in re.finditer(r"\b\w+\b", text)
                                 if match.group().lower() in abandonment_words}
        # Normal runs can span an entire sentence. Select space boundaries
        # explicitly so pauses do not depend on a typo splitting that run.
        thinking_pause_positions = {pos for pos, char in enumerate(text)
                                    if pos > 0 and char == " "
                                    and self.engine.should_thinking_pause()}

        i = 0
        while i < len(text):
            self._check_cancelled()
            if self._abandon_count >= abandonment_cfg.max_per_session:
                abandonment_positions.clear()
            # Check for rewrite at this word boundary
            if i in rewrite_positions:
                granularity = rewrite_positions[i]
                rewrite_actions, rewrite_chars, skip = self._build_rewrite(
                    text, i, granularity=granularity, depth=0,
                    total_paste_chars=total_paste_chars,
                )
                if skip > 0:
                    actions.extend(rewrite_actions)
                    char_count += rewrite_chars
                    i += skip
                    self._char_position += skip
                    continue
                # Couldn't generate a different draft — remove and fall through
                del rewrite_positions[i]

            # --- Word abandonment (Feature 5) ---
            abandon_entry = self._check_word_abandonment(text, i)
            if abandon_entry:
                actions.append(AbandonWord(
                    partial_text=abandon_entry["partial"],
                    replacement_text=abandon_entry["replacement"],
                ))
                char_count += len(abandon_entry["replacement"])
                i += abandon_entry["skip"]
                self._abandon_count += 1
                self._char_position += abandon_entry["skip"]
                continue
            # A rejected candidate is consumed normally, without rerolling it.
            abandonment_positions.discard(i)

            # Check for whole-word misspelling at this position
            if i in word_misspells:
                wrong, correct, word_len = word_misspells[i]
                misspell_actions, extra_skip = self._build_word_misspelling(wrong, correct, text[i + word_len:])
                actions.extend(misspell_actions)
                char_count += len(correct) + extra_skip
                i += word_len + extra_skip
                self._char_position += word_len + extra_skip
                continue

            # Check for single-char mistake (adjacent key misclick)
            if i in mistake_positions:
                mistake_actions, mistake_chars, uncorrected = self._build_mistake(text, i)
                if uncorrected:
                    # Anchor to the actual emitted action. Replay moves this
                    # marker through earlier insertions/deletions/autocorrects.
                    offset = 1 if uncorrected[1] == "" else 0
                    for typed in mistake_actions:
                        if isinstance(typed, TypeText) and typed.text[offset:offset + len(uncorrected[0])] == uncorrected[0]:
                            typed.proofread_typo = (*uncorrected, offset)
                            break
                actions.extend(mistake_actions)
                char_count += mistake_chars
                i += mistake_chars
                self._char_position += mistake_chars
                continue

            # Random thinking pause mid-chunk
            if i in thinking_pause_positions:
                actions.append(Pause(duration=self.engine.thinking_pause_duration()))
                thinking_pause_positions.discard(i)

            # Normal typing — accumulate a run of non-mistake characters
            run_start = i
            while (
                i < len(text)
                and i not in mistake_positions
                and i not in rewrite_positions
                and i not in word_misspells
                and i not in abandonment_positions
                and i not in thinking_pause_positions
            ):
                i += 1
            run_text = text[run_start:i]
            if run_text:
                # --- Word speed + Quote detection (Features 1, 2, 10) ---
                # Split run into words and assign per-word speed multipliers
                word_actions = self._build_word_speed_actions(run_text)
                actions.extend(word_actions)
                char_count += len(run_text)

                # --- Autocorrect tracking (Feature 12) ---
                self._track_autocorrect_words(run_text, actions)

                # Research: 35-44% of backspace presses are false alarms.
                # Occasionally backspace correct text then retype it.
                if text.isascii() and len(run_text) >= 3 and self.engine.should_false_alarm():
                    fa_chars = min(self.engine.false_alarm_chars(), len(run_text))
                    deleted_text = run_text[-fa_chars:]
                    actions.append(Pause(duration=self._rng.uniform(0.2, 0.5)))
                    actions.append(Rewrite.simple(
                        delete_count=fa_chars,
                        text=deleted_text,
                        description=f"False alarm: delete {fa_chars} correct chars, retype",
                    ))

            self._char_position += (i - run_start) if i > run_start else 0

        # --- Post-chunk pauses ---
        if chunk.is_sentence_end:
            actions.append(Pause(duration=self.engine.sentence_pause_duration()))
        if chunk.is_paragraph_end:
            actions.append(Pause(duration=self.engine.paragraph_pause_duration()))

        return actions, char_count, uncorrected_typos

    # ------------------------------------------------------------------
    # Proofreading (arrow back to fix uncorrected typos after a sentence)
    # ------------------------------------------------------------------

    def _build_proofread(
        self, typos: list[tuple[str, str, int]], total_chars_typed: int,
        known_text: str | None = None,
    ) -> list[TypingAction]:
        """Correct only verified emitted typo characters with relative moves."""
        if known_text is None or not known_text.isascii():
            return []
        actions = []
        text = known_text
        # Correct right to left so deletions do not shift earlier positions.
        for wrong, correct, offset in sorted(typos, key=lambda t: t[2], reverse=True):
            distance = total_chars_typed - offset
            pos = len(known_text) - distance
            if not 1 <= distance <= self.profile.proofread.max_proofread_distance:
                continue
            if not (0 <= pos < len(text)) or text[pos:pos + len(wrong)] != wrong:
                continue
            if not wrong.isascii() or not correct.isascii():
                continue
            tail = len(text) - pos - len(wrong)
            actions.append(Pause(duration=self._r(self.profile.proofread.found_typo_pause), description="Found a typo"))
            actions.extend(PressKey(key="left") for _ in range(len(text) - pos))
            actions.extend(ApplyFormatting(shortcut=("shift", "right")) for _ in wrong)
            actions.append(TypeText(text=correct) if correct else PressKey(key="backspace"))
            actions.extend(PressKey(key="right") for _ in range(tail))
            text = text[:pos] + correct + text[pos + len(wrong):]
        return actions

    # ------------------------------------------------------------------
    # Revisiting earlier text (go back and revise previous paragraphs)
    # ------------------------------------------------------------------

    def _maybe_build_revisit(
        self, typed_so_far: str, total_paste_chars: int,
    ) -> list[TypingAction]:
        """Possibly build a revisit sequence to go back and edit earlier text.

        Called at paragraph boundaries. Uses AI to pick what to revise.
        """
        self._check_cancelled()
        if not hasattr(self, '_revisit_count'):
            self._revisit_count = 0

        max_revisits = getattr(self.settings, 'revisit_max_per_session', 5)
        if self._revisit_count >= max_revisits:
            return []
        # Rejected/failed AI proposals still cost a request. Non-ASCII cursor
        # edits are unsupported, so do not request proposals we cannot execute.
        if (not typed_so_far.isascii()
                or getattr(self, "_revisit_requests", 0) >= min(max_revisits, self.MAX_REVISIT_REQUESTS_PER_PLAN)):
            return []

        # Scale probability with text length — more text = more likely to revisit
        base_prob = getattr(self.settings, 'revisit_probability', 0.20)
        # Boost for longer text
        length_boost = min(total_paste_chars / self.profile.proofread.revisit_length_boost_divisor, 1.5)
        prob = base_prob * length_boost

        if self._rng.random() > prob:
            return []

        if not self._ai_rewriter or not self._ai_rewriter.is_enabled:
            return []

        # Ask AI to pick revision targets from what's been typed so far
        self._check_cancelled()
        self._revisit_requests = getattr(self, "_revisit_requests", 0) + 1
        targets = self._ai_rewriter.pick_revisit_targets(
            typed_so_far[-2048:], num_targets=self._rng.randint(1, 2)
        )
        self._check_cancelled()

        if not targets:
            return []

        actions: list[TypingAction] = []

        for target in targets:
            original = target.get("original", "")
            revised = target.get("revised", "")

            if not original or not revised or original == revised:
                continue

            revisit_actions = self._build_revisit(typed_so_far, original, revised)
            if revisit_actions:
                actions.extend(revisit_actions)
                typed_so_far = PlannedText(typed_so_far).apply(revisit_actions).text
                self._revisit_count += 1
                if self._revisit_count >= max_revisits:
                    break

        return actions

    def _build_revisit(
        self, typed_so_far: str, original: str, revised: str,
    ) -> list[TypingAction]:
        """Revise a unique emitted span and return to our insertion cursor."""
        edits = replace_known_span(
            typed_so_far, original, revised,
            min_distance=self.profile.proofread.revisit_min_distance,
        )
        if not edits:
            return []
        return [Pause(
            duration=self._r(self.profile.proofread.revisit_re_reading_pause),
            description="Re-reading earlier text, reconsidering",
        ), *edits, Pause(
            duration=self._r(self.profile.proofread.revisit_resume_pause),
            description="Resuming typing after revisit",
        )]

    # ------------------------------------------------------------------
    # Word-level misspelling (type wrong word, notice, fix)
    # ------------------------------------------------------------------

    def _build_word_misspelling(
        self, wrong: str, correct: str, trailing_text: str = ""
    ) -> tuple[list[TypingAction], int]:
        """Type a misspelled word, pause as if noticing, backspace only to
        where the word diverges, then retype the rest correctly.

        Returns (actions, extra_skip) where extra_skip is the number of
        characters after the word that were already typed (e.g. 1 for space).
        """
        actions: list[TypingAction] = []

        # Find where wrong and correct diverge
        common = 0
        for w, c in zip(wrong, correct):
            if w == c:
                common += 1
            else:
                break

        # The suffix that needs fixing
        wrong_suffix = wrong[common:]
        correct_suffix = correct[common:]

        # If wrong is a prefix of correct (or identical), fall back to
        # deleting the whole word and retyping to avoid a zero-length delete.
        if not wrong_suffix:
            wrong_suffix = wrong
            correct_suffix = correct
            common = 0

        # Type the wrong word
        actions.append(TypeText(text=wrong))

        # Sometimes notice immediately, sometimes type a space first then notice
        if trailing_text.startswith(" ") and self._rng.random() < self.profile.misspelling.notice_after_space_probability:
            # Type the space after the word, then notice
            actions.append(TypeText(text=" "))
            actions.append(Pause(duration=self._r(self.profile.misspelling.notice_after_space_pause)))
            # Backspace the space + wrong suffix only
            actions.append(Rewrite.simple(
                delete_count=len(wrong_suffix) + 1,
                text=correct_suffix + " ",
            ))
            return actions, 1  # consumed the trailing space
        else:
            # Notice right at the end of the word
            actions.append(Pause(duration=self._r(self.profile.misspelling.notice_immediately_pause)))
            # Backspace only the wrong suffix
            actions.append(Rewrite.simple(
                delete_count=len(wrong_suffix),
                text=correct_suffix,
            ))
            return actions, 0

    # ------------------------------------------------------------------
    # Mistake planning (single-char adjacent key misclicks)
    # ------------------------------------------------------------------

    def _pick_mistake_positions(self, text: str) -> set[int]:
        """Choose which character positions in `text` will have typos."""
        positions: set[int] = set()
        for i, char in enumerate(text):
            if not char.isalpha():
                continue
            if self._rng.random() < self.settings.error_rate:
                positions.add(i)
        return positions

    def _build_mistake(self, text: str, pos: int) -> tuple[list[TypingAction], int, tuple[str, str] | None]:
        """Build actions for a single typo at position `pos`.

        Returns (actions, chars_consumed, uncorrected_info).
        uncorrected_info is (wrong_char, correct_char) if the typo was left in, else None.
        """
        actions: list[TypingAction] = []
        intended_char = text[pos]
        typo_char = self.engine.generate_typo(intended_char)

        # Reject wrong-shift typos mid-word — a real person doesn't type "tHe".
        # Wrong-shift only makes sense at word start (pos==0 or previous char is
        # whitespace/punctuation).
        is_word_start = pos == 0 or not text[pos - 1].isalpha()
        if (
            not is_word_start
            and typo_char
            and len(typo_char) == 1
            and typo_char == intended_char.swapcase()
        ):
            # Re-roll as an adjacent-key typo instead
            typo_char = self.engine.generate_typo(intended_char)
            # If we got wrong_shift again, just type normally
            if typo_char and len(typo_char) == 1 and typo_char == intended_char.swapcase():
                typo_char = intended_char

        if typo_char == intended_char or not typo_char:
            # Couldn't generate a good typo — just type normally
            actions.append(TypeText(text=intended_char))
            return actions, 1, None

        # Double-strike: typo_char is two copies of intended_char (e.g. "hh")
        is_double = len(typo_char) == 2 and typo_char == intended_char + intended_char

        # ~8% of typos go unnoticed
        if self._rng.random() < self.profile.mistakes.unnoticed_rate:
            actions.append(TypeText(text=typo_char))
            # For double-strike left uncorrected, the first char IS correct
            if is_double:
                return actions, 1, (typo_char[1], "")
            return actions, 1, (typo_char, intended_char)

        # --- Feature 4: Dual-loop error correction ---
        # Fast loop: immediate motor correction (~100-200ms, no extra chars typed)
        # Slow loop: cognitive correction (visual search, chars typed before noticing)
        if self.engine.is_fast_loop_correction():
            # Fast motor loop — fingers catch the mistake almost instantly
            actions.append(TypeText(text=typo_char))
            actions.append(Pause(duration=self.engine.fast_loop_pause()))
            actions.append(Rewrite.simple(
                delete_count=len(typo_char),
                text=intended_char,
                description="Fast motor correction",
            ))
            return actions, 1, None

        # Slow cognitive loop — type extra chars before noticing
        chars_after = self.engine.chars_before_noticing_mistake()
        extra_text = text[pos + 1: pos + 1 + chars_after]

        wrong_text = typo_char + extra_text
        correct_text = intended_char + extra_text

        # For slow loop with delayed notice, add visual search pause proportional to distance
        if chars_after > 0:
            actions.append(MakeMistake(
                wrong_text=wrong_text,
                correct_text=correct_text,
                chars_before_noticing=len(extra_text),
            ))
        else:
            # Immediate notice but slow loop — slightly longer pause than fast loop
            actions.append(MakeMistake(
                wrong_text=wrong_text,
                correct_text=correct_text,
                chars_before_noticing=0,
            ))

        # The MakeMistake action consumes the intended char AND the extra chars
        return actions, 1 + len(extra_text), None

    def _pick_rewrite_positions(
        self, text: str, total_paste_chars: int = 500
    ) -> list[tuple[int, str]]:
        """Pick zero or more positions for rewrite actions with granularity tags.

        Returns list of (position, granularity) where granularity is
        'word', 'sentence', or 'paragraph'.
        No minimum spacing constraint — rewrites can be back-to-back.
        """
        positions: list[tuple[int, str]] = []

        # Find word boundary positions
        word_starts: list[int] = []
        for m in re.finditer(r"\b\w", text):
            pos = m.start()
            if pos > 3:
                word_starts.append(pos)

        if not word_starts:
            return positions

        # Find sentence start positions for granularity validation
        sentence_starts: set[int] = set()
        for m in re.finditer(r"(?<=[.!?]\s)\S", text):
            sentence_starts.add(m.start())
        # Also include position 0 and positions after newlines
        sentence_starts.add(0)
        for m in re.finditer(r"\n\s*\S", text):
            sentence_starts.add(m.end() - 1)

        for pos in word_starts:
            if self.engine.should_rewrite(total_paste_chars):
                granularity = self.engine.pick_rewrite_granularity()
                # Sentence/paragraph rewrites only make sense at sentence boundaries
                if granularity in ("sentence", "paragraph") and pos not in sentence_starts:
                    granularity = "word"
                positions.append((pos, granularity))

        return positions

    def _get_ai_draft(self, final_text: str, context: str = "") -> str | None:
        """Lazily request a unique draft within this plan's hard call budget."""
        self._check_cancelled()
        # Repeat rewrites delete the restored source too. Code-point counts
        # cannot safely predict native deletion units for Unicode graphemes.
        if not final_text.isascii() or not final_text.isprintable():
            return None
        if final_text in self._draft_cache:
            return self._draft_cache[final_text]
        if (not self._ai_rewriter or not self._ai_rewriter.is_enabled
                or self._draft_requests >= self.MAX_DRAFT_REQUESTS_PER_PLAN):
            return None
        self._check_cancelled()
        self._draft_requests += 1
        # Cache failures as well: an unavailable draft must not repeatedly spend
        # the budget on the same span. AIRewriter handles API failures locally.
        self._draft_cache[final_text] = None
        draft = self._ai_rewriter.generate_first_draft(final_text, context)
        self._check_cancelled()
        if (isinstance(draft, str) and draft and draft != final_text
                and draft.isascii() and draft.isprintable()):
            self._draft_cache[final_text] = draft
        return self._draft_cache[final_text]

    def _extract_span(self, text: str, pos: int, granularity: str) -> str | None:
        """Extract the text span for a rewrite at the given position and granularity."""
        remaining = text[pos:]

        if granularity == "word":
            word_count = self.engine.rewrite_word_count()
            match = re.match(r"(?:\s*\S+){1," + str(word_count) + r"}", remaining)
            if match:
                return match.group(0).lstrip()
            return None

        elif granularity == "sentence":
            # Grab to end of sentence
            match = re.match(r"[^.!?\n]*[.!?]", remaining)
            if match:
                return match.group(0).strip()
            # No sentence end found — grab rest of line
            match = re.match(r"[^\n]+", remaining)
            if match:
                return match.group(0).strip()
            return None

        elif granularity == "paragraph":
            # Grab to end of paragraph (next double newline or end)
            match = re.match(r"[^\n]*(?:\n(?!\n)[^\n]*)*", remaining)
            if match:
                return match.group(0).strip()
            return None

        return None

    @staticmethod
    def _common_prefix_len(a: str, b: str) -> int:
        """Return the length of the common prefix between two strings."""
        limit = min(len(a), len(b))
        for i in range(limit):
            if a[i] != b[i]:
                return i
        return limit

    def _partial_rewrite(self, old_text: str, new_text: str) -> Rewrite:
        """Build a Rewrite that only deletes back to where old and new diverge.

        A real person doesn't delete an entire sentence to retype it — they
        backspace to the point where the text needs to change, then type
        the new suffix from there.
        """
        common = self._common_prefix_len(old_text, new_text)
        delete_count = len(old_text) - common
        new_suffix = new_text[common:]
        return Rewrite(
            delete_count=delete_count,
            new_actions=[TypeText(text=new_suffix)] if new_suffix else [],
        )

    def _build_rewrite(
        self, text: str, pos: int, granularity: str = "word",
        depth: int = 0, total_paste_chars: int = 500,
    ) -> tuple[list[TypingAction], int, int]:
        """Build a rewrite action with optional cascading nested rewrites.

        Returns (actions, char_count_of_new_text, chars_to_skip_in_original).
        """
        actions: list[TypingAction] = []

        # Extract the span to rewrite based on granularity
        remaining = text[pos:]

        if granularity == "word":
            word_count = self.engine.rewrite_word_count()
            match = re.match(r"(?:\s*\S+){1," + str(word_count) + r"}", remaining)
        elif granularity == "sentence":
            match = re.match(r"[^.!?\n]*[.!?](?:\s|$)?", remaining)
            if not match:
                match = re.match(r"[^\n]+", remaining)
        elif granularity == "paragraph":
            match = re.match(r"[^\n]*(?:\n(?!\n)[^\n]*)*", remaining)
        else:
            match = None

        if not match:
            return [], 0, 0

        original_span = match.group(0)
        leading_ws = original_span[: len(original_span) - len(original_span.lstrip())]
        final_text = original_span.lstrip()

        if not final_text or len(final_text) < 2:
            return [], 0, 0

        # Type any leading whitespace before the rewrite
        if leading_ws:
            actions.append(TypeText(text=leading_ws))

        # Get AI-generated rough draft
        context_start = max(0, pos - 100)
        context = text[context_start:pos]
        draft_text = self._get_ai_draft(final_text, context)

        # If no draft available, skip the rewrite
        if not draft_text or draft_text == final_text:
            return [], 0, 0

        # Type the rough draft first
        actions.append(TypeText(text=draft_text))

        # Pause as if re-reading and reconsidering
        pause_duration = self._r(self.profile.rewrite.word_pause)
        if granularity == "paragraph":
            pause_duration = self._r(self.profile.rewrite.paragraph_pause)
        elif granularity == "sentence":
            pause_duration = self._r(self.profile.rewrite.sentence_pause)
        actions.append(Pause(duration=pause_duration))

        # Only delete back to where draft and final diverge, then retype the
        # suffix.  For cascading rewrites the suffix may itself contain
        # sub-rewrites, so we build cascading actions for the divergent part.
        common = self._common_prefix_len(draft_text, final_text)
        delete_count = len(draft_text) - common
        new_suffix = final_text[common:]

        if new_suffix:
            new_actions = self._build_cascading_actions(
                new_suffix, depth=depth, total_paste_chars=total_paste_chars,
                context=context,
            )
        else:
            new_actions = []

        actions.append(Rewrite(
            delete_count=delete_count,
            new_actions=new_actions,
        ))

        # Handle repeat rewrites (same spot rewritten 2-3x)
        # Track what's currently on screen after each rewrite
        current_text = final_text
        repeat_count = 0
        while (
            repeat_count < self.settings.rewrite_max_repeats
            and self.engine.should_repeat_rewrite()
        ):
            repeat_count += 1
            # Generate another draft for the same text
            # Use a slightly different prompt by adding repeat context
            repeat_draft = self._get_ai_draft(
                final_text + f" [repeat{repeat_count}]",
                context + f" (rewriting again, attempt {repeat_count + 1})",
            )
            if not repeat_draft or repeat_draft == final_text:
                break

            # Rewrite current_text → repeat_draft (only the divergent suffix)
            actions.append(Pause(duration=self._r(self.profile.rewrite.repeat_pause)))
            actions.append(self._partial_rewrite(current_text, repeat_draft))

            # Rewrite repeat_draft → final_text (only the divergent suffix)
            actions.append(Pause(duration=self._r(self.profile.rewrite.repeat_final_pause)))
            actions.append(self._partial_rewrite(repeat_draft, final_text))

            current_text = final_text

        # Skip the exact span in the original text
        chars_to_skip = len(original_span)
        chars_to_skip = min(chars_to_skip, len(text) - pos)

        return actions, len(leading_ws) + len(final_text), chars_to_skip

    def _build_cascading_actions(
        self, final_text: str, depth: int = 0,
        total_paste_chars: int = 500, context: str = "",
    ) -> list[TypingAction]:
        """Build actions for retyping text, potentially with nested rewrites.

        depth: recursion depth (cap at 2 to prevent infinite nesting)
        """
        # Base case: no cascading at max depth or for very short text
        if depth >= self.profile.rewrite.cascade_max_depth or len(final_text) < self.profile.rewrite.cascade_min_text_length or not self.engine.should_cascade():
            return [TypeText(text=final_text)]

        # Pick sub-rewrite positions within this text
        sub_positions = self._pick_rewrite_positions(final_text, total_paste_chars)

        # Reduce density at deeper levels
        if depth > 0:
            sub_positions = [p for p in sub_positions if self._rng.random() < self.profile.rewrite.deep_level_density_reduction]

        # At deeper levels, only allow word-level rewrites
        if depth >= 1:
            sub_positions = [(pos, "word") for pos, _ in sub_positions]

        if not sub_positions:
            return [TypeText(text=final_text)]

        actions: list[TypingAction] = []
        i = 0

        for pos, granularity in sub_positions:
            if pos < i:
                continue  # skip overlapping positions

            # Type text up to this position
            if pos > i:
                actions.append(TypeText(text=final_text[i:pos]))

            # Build the sub-rewrite
            sub_actions, sub_chars, skip = self._build_rewrite(
                final_text, pos, granularity=granularity,
                depth=depth + 1, total_paste_chars=total_paste_chars,
            )

            if skip > 0:
                actions.extend(sub_actions)
                i = pos + skip
            else:
                # Couldn't build sub-rewrite, just advance past this position
                i = pos

        # Type remaining text
        if i < len(final_text):
            actions.append(TypeText(text=final_text[i:]))

        return actions if actions else [TypeText(text=final_text)]

    # ------------------------------------------------------------------
    # Feature 1/2: Word speed + capitalization difficulty
    # ------------------------------------------------------------------

    @staticmethod
    def _word_speed_key(word: str) -> str:
        # Whitespace tokenization retains sentence punctuation and quotation
        # marks. Remove those wrappers for lookup, never from the emitted text.
        # Keep symbols such as + and # significant for terms like C++ and C#.
        return word.lower().strip(".,!?;:()[]{}<>\"'“”‘’«»…—–")

    def _get_word_speed(self, word: str) -> float:
        """Look up per-word speed multiplier from behavioral_content.

        Returns 1.0 (normal speed) if no entry found.
        Builds a lookup cache on first access.
        """
        if self._word_speed_cache is None:
            self._word_speed_cache = {}
            for entry in self._behavioral_content.get("word_speed_map", []):
                w = entry.get("word", "")
                if w:
                    try:
                        factor = float(entry.get("multiplier", 1.0))
                    except (TypeError, ValueError):
                        factor = 1.0
                    self._word_speed_cache[self._word_speed_key(w)] = (
                        factor if math.isfinite(factor) and 0.1 <= factor <= 10.0 else 1.0
                    )
        return self._word_speed_cache.get(self._word_speed_key(word), 1.0)

    def _build_word_speed_actions(self, run_text: str) -> list[TypingAction]:
        """Split a run of text into word-boundary segments with per-word speed.

        Also applies: quote speed (Feature 10), pre-word pauses (Feature 2),
        syllable pauses (Feature 3), composition mode (Feature 8).
        """
        bc = self._behavioral_content
        word_speed_map = bc.get("word_speed_map", [])
        quote_ranges = bc.get("quote_ranges", [])

        # If no behavioral data at all, emit a single TypeText
        if not word_speed_map and not quote_ranges and not bc:
            return [TypeText(text=run_text)]

        actions: list[TypingAction] = []
        # Split into (word, separator) pairs preserving all characters
        tokens = re.split(r"(\s+)", run_text)

        token_position = self._char_position
        for token in tokens:
            if not token:
                continue
            if token.isspace():
                actions.append(TypeText(text=token))
                token_position += len(token)
                continue

            # Determine speed multiplier
            # The AI word map describes delay factors (>1 = harder/slower),
            # whereas TypeText and quote/composition profiles describe speed.
            multiplier = 1.0 / self._get_word_speed(token)

            # Quote speed override (Feature 10)
            quote_mult = self._get_quote_multiplier(token_position)
            if quote_mult is not None:
                multiplier = min(multiplier, quote_mult)

            # Feature 8: Composition mode speed adjustment
            comp_mult = self._get_composition_multiplier(token_position)
            if comp_mult != 1.0:
                multiplier *= comp_mult

            # Feature 2: Pre-word pause for difficult words
            pre_pause = self._get_pre_word_pause(token)
            if pre_pause > 0:
                actions.append(Pause(duration=pre_pause, description=f"Hesitating before '{token[:15]}'"))

            # Feature 3: Syllable-boundary pauses — split word into syllable chunks
            syllable_actions = self._build_syllable_actions(token, multiplier)
            if syllable_actions:
                actions.extend(syllable_actions)
            elif multiplier != 1.0:
                actions.append(TypeText(text=token, speed_multiplier=multiplier))
            else:
                actions.append(TypeText(text=token))

            # Feature 8: Composition clause-boundary pause
            clause_pause = self._get_composition_clause_pause(token, token_position)
            if clause_pause > 0:
                actions.append(Pause(duration=clause_pause, description="Composing next clause"))

            # Source-glance pause (Feature 10) — occasional brief pause when in a quote
            if quote_mult is not None and self._rng.random() < self.profile.behaviors.quote.source_glance_frequency:
                actions.append(Pause(
                    duration=self._r(self.profile.behaviors.quote.source_glance_pause),
                    description="Glancing at source",
                ))

            token_position += len(token)

        # Merge adjacent TypeText actions with the same speed_multiplier for efficiency
        merged: list[TypingAction] = []
        for action in actions:
            if (
                merged
                and isinstance(action, TypeText)
                and isinstance(merged[-1], TypeText)
                and action.speed_multiplier == merged[-1].speed_multiplier
            ):
                merged[-1] = TypeText(
                    text=merged[-1].text + action.text,
                    speed_multiplier=action.speed_multiplier,
                )
            else:
                merged.append(action)

        return merged if merged else [TypeText(text=run_text)]

    # ------------------------------------------------------------------
    # Feature 2: Pre-word difficulty pause
    # ------------------------------------------------------------------

    def _get_pre_word_pause(self, word: str) -> float:
        """Return a pre-word pause duration based on word difficulty, or 0.0."""
        cfg = self.profile.behaviors.pre_word_pause
        if not cfg.enabled:
            return 0.0

        # Look up word difficulty from behavioral content
        difficulty = self._get_word_difficulty(word)
        if difficulty < cfg.difficulty_threshold:
            return 0.0

        if difficulty >= 0.8:
            return self._r(cfg.very_hard_word_pause)
        elif difficulty >= 0.6:
            return self._r(cfg.hard_word_pause)
        else:
            return self._r(cfg.base_pause)

    def _get_word_difficulty(self, word: str) -> float:
        """Look up word difficulty from AI behavioral content.

        Returns 0.0 (easy) to 1.0 (very hard). Defaults to 0.0 if not found.
        Uses word_difficulty_ratings from behavioral content if available,
        falls back to speed multiplier as a proxy.
        """
        # Check explicit difficulty ratings first
        ratings = self._behavioral_content.get("word_difficulty_ratings", [])
        lower = word.lower().strip(".,!?;:")
        for entry in ratings:
            if entry.get("word", "").lower() == lower:
                return entry.get("difficulty", 0.0)

        # Fall back: use speed multiplier as proxy (>1.0 = harder)
        speed = self._get_word_speed(word)
        if speed > 1.0:
            return min((speed - 1.0) * 2.0, 1.0)  # 1.5x speed → 1.0 difficulty
        return 0.0

    # ------------------------------------------------------------------
    # Feature 3: Syllable-boundary micro-pauses
    # ------------------------------------------------------------------

    def _build_syllable_actions(self, word: str, multiplier: float) -> list[TypingAction] | None:
        """Split a word at syllable boundaries with micro-pauses between syllables.

        Returns None if no syllable data is available for this word.
        """
        syllables = self._get_syllables(word)
        if not syllables or len(syllables) <= 1:
            return None

        actions: list[TypingAction] = []
        for i, syl in enumerate(syllables):
            if multiplier != 1.0:
                actions.append(TypeText(text=syl, speed_multiplier=multiplier))
            else:
                actions.append(TypeText(text=syl))
            # Add micro-pause between syllables (not after the last one)
            if i < len(syllables) - 1:
                pause_mult = self._r(self.profile.keystroke.syllable_pause_multiplier)
                # Convert multiplier to a tiny pause: base IKI × (multiplier - 1)
                base_iki = 60.0 / (self.engine.settings.wpm * 5)
                micro_pause = base_iki * (pause_mult - 1.0)
                if micro_pause > 0.005:  # only add if noticeable
                    actions.append(Pause(duration=micro_pause))
        return actions

    def _get_syllables(self, word: str) -> list[str] | None:
        """Get syllable breakdown for a word from AI behavioral content.

        Returns a list of syllable strings, or None if not available.
        """
        syllable_data = self._behavioral_content.get("syllable_boundaries", [])
        if not syllable_data:
            return None

        lower = word.lower().strip(".,!?;:")
        for entry in syllable_data:
            if entry.get("word", "").lower() == lower:
                syllables = entry.get("syllables", [])
                if syllables and len(syllables) > 1:
                    # Map syllables back to original casing
                    return self._map_syllables_to_original(word, syllables)
        return None

    @staticmethod
    def _map_syllables_to_original(original: str, syllables: list[str]) -> list[str]:
        """Map lowercase syllables back to the original word's casing."""
        result = []
        pos = 0
        for syl in syllables:
            end = pos + len(syl)
            if end <= len(original):
                result.append(original[pos:end])
            else:
                result.append(original[pos:])
            pos = end
        # If syllables didn't cover the full word, append remainder
        if pos < len(original):
            if result:
                result[-1] += original[pos:]
            else:
                result.append(original[pos:])
        return result

    # ------------------------------------------------------------------
    # Feature 8: Composition mode
    # ------------------------------------------------------------------

    def _get_composition_multiplier(self, char_position: int) -> float:
        """Return speed multiplier based on whether we're composing or copy-typing."""
        cfg = self.profile.behaviors.composition_mode
        if not cfg.enabled:
            return 1.0

        annotations = self._behavioral_content.get("composition_annotations", [])
        if not annotations:
            return 1.0

        for ann in annotations:
            start = ann.get("start", -1)
            end = ann.get("end", -1)
            if start <= char_position < end:
                mode = ann.get("mode", "copy")
                if mode == "composition":
                    return cfg.composition_speed_multiplier
                elif mode == "copy":
                    return cfg.copy_typing_speed_multiplier
        return 1.0

    def _get_composition_clause_pause(self, token: str, char_position: int | None = None) -> float:
        """Return a clause-boundary pause if we're in composition mode and at a clause end."""
        cfg = self.profile.behaviors.composition_mode
        if not cfg.enabled:
            return 0.0

        annotations = self._behavioral_content.get("composition_annotations", [])
        if not annotations:
            return 0.0

        # Check the actual token position within this run.
        if char_position is None:
            char_position = self._char_position
        in_composition = False
        for ann in annotations:
            start = ann.get("start", -1)
            end = ann.get("end", -1)
            if start <= char_position < end and ann.get("mode") == "composition":
                in_composition = True
                break

        if not in_composition:
            return 0.0

        # Check if token ends with clause-ending punctuation
        stripped = token.rstrip()
        if stripped and stripped[-1] in ",;:—–":
            return self._r(cfg.clause_pause)
        elif stripped and stripped[-1] in ".!?":
            return self._r(cfg.sentence_composition_pause)
        return 0.0

    # ------------------------------------------------------------------
    # Feature 5: Mid-word abandonment
    # ------------------------------------------------------------------

    def _check_word_abandonment(self, text: str, pos: int) -> dict | None:
        """Check if the word at `pos` should be abandoned mid-typing.

        Returns {"partial": str, "replacement": str, "skip": int} or None.
        """
        cfg = self.profile.behaviors.abandonment
        if pos and (text[pos - 1].isalnum() or text[pos - 1] == "_"):
            return None
        if not cfg.enabled or cfg.probability_per_word <= 0:
            return None
        if self._abandon_count >= cfg.max_per_session:
            return None

        abandonments = self._behavioral_content.get("word_abandonments", [])
        if not abandonments:
            return None

        # Extract the word at this position
        match = _WORD_RE.match(text, pos)
        if not match:
            return None
        current_word = match.group(0)
        if not current_word.isascii():
            return None

        for entry in abandonments:
            if entry.get("word", "").lower() == current_word.lower():
                abandon_after = entry.get("abandon_after_chars", len(current_word) // 2)
                replacement = entry.get("replacement", current_word)
                if abandon_after < 1 or abandon_after >= len(current_word):
                    continue
                if self._rng.random() >= cfg.probability_per_word:
                    return None
                return {
                    "partial": current_word[:abandon_after],
                    "replacement": replacement,
                    "skip": len(current_word),
                }

        return None

    # ------------------------------------------------------------------
    # Feature 6: Sentence restructuring
    # ------------------------------------------------------------------

    def _should_restructure(self, chunk_text: str) -> bool:
        """Check if sentence restructuring is enabled and under budget."""
        cfg = self.profile.behaviors.restructuring
        if not cfg.enabled:
            return False
        if self._restructure_count >= cfg.max_per_session:
            return False
        return True

    def _find_restructure_match(self, chunk_text: str) -> dict | None:
        """Find a sentence restructure entry matching this chunk's text."""
        restructures = self._behavioral_content.get("sentence_restructures", [])
        if not restructures:
            return None

        chunk_lower = chunk_text.strip().lower()
        for entry in restructures:
            original = entry.get("original_sentence", "").strip().lower()
            first_draft = entry.get("first_draft", "")
            if not original or not first_draft:
                continue
            # Match if the chunk text starts with the original sentence
            if chunk_lower.startswith(original) or original.startswith(chunk_lower):
                return entry
        return None

    # ------------------------------------------------------------------
    # Feature 7: Distraction pauses
    # ------------------------------------------------------------------

    def _maybe_insert_distraction(self, char_position: int) -> DistractionPause | None:
        """Maybe insert a distraction pause at the current position.

        Checks:
        - Feature enabled
        - min_interval_chars since last distraction
        - Finds closest distraction point within 50 chars
        - Rolls probability based on quality
        - Picks duration tier using weighted random
        """
        cfg = self.profile.behaviors.distraction
        if not cfg.enabled:
            return None
        if self._chars_since_distraction < cfg.min_interval_chars:
            return None

        distraction_points = self._behavioral_content.get("distraction_points", [])
        if not distraction_points:
            return None

        # Find closest distraction point within 50 chars
        closest = None
        closest_dist = 999999
        for dp in distraction_points:
            dp_pos = dp.get("position", -1)
            dist = abs(dp_pos - char_position)
            if dist < closest_dist and dist <= 50:
                closest = dp
                closest_dist = dist

        if closest is None:
            return None

        # Roll probability based on quality
        quality = closest.get("quality", "low")
        quality_probs = {"high": 1.0, "medium": 0.6, "low": 0.3}
        prob = cfg.probability_per_break_point * quality_probs.get(quality, 0.3)
        if self._rng.random() > prob:
            return None

        # Pick duration tier using weighted random
        weights = [cfg.short_weight, cfg.medium_weight, cfg.long_weight, cfg.very_long_weight]
        durations = [cfg.short_duration, cfg.medium_duration, cfg.long_duration, cfg.very_long_duration]
        tier_names = ["phone_check", "zone_out", "social_media", "stretch"]

        # Weighted selection
        total_weight = sum(weights)
        roll = self._rng.random() * total_weight
        cumulative = 0.0
        selected_idx = 0
        for idx, w in enumerate(weights):
            cumulative += w
            if roll <= cumulative:
                selected_idx = idx
                break

        duration = self._r(durations[selected_idx])
        distraction_type = tier_names[selected_idx]

        self._chars_since_distraction = 0
        self._distraction_count += 1

        return DistractionPause(
            duration=duration,
            distraction_type=distraction_type,
        )

    # ------------------------------------------------------------------
    # Feature 9: Formatting hesitation
    # ------------------------------------------------------------------

    def _maybe_add_formatting_hesitation(self, actions: list[TypingAction], format_key: str) -> None:
        """Add a hesitation pause before a formatting shortcut based on familiarity."""
        cfg = self.profile.behaviors.formatting_hesitation
        if not cfg.enabled:
            return

        familiarity = cfg.familiarity_ratings.get(format_key, 0.5)
        # Low familiarity = longer pause. Scale: familiarity 0.0 -> max_pause, 1.0 -> base_pause
        if familiarity >= 0.95:
            return  # Very familiar, no hesitation

        base = self._r(cfg.base_pause)
        max_p = self._r(cfg.max_pause)
        # Interpolate: unfamiliarity factor (1 - familiarity) scales between base and max
        duration = base + (max_p - base) * (1.0 - familiarity)

        actions.append(Pause(
            duration=duration,
            description=f"Hesitating before {format_key} shortcut",
        ))

    # ------------------------------------------------------------------
    # Feature 10: Quote detection
    # ------------------------------------------------------------------

    def _get_quote_multiplier(self, char_position: int) -> float | None:
        """Return the quote speed multiplier if char_position is within a quote range.

        Returns None if not in a quote range.
        """
        quote_ranges = self._behavioral_content.get("quote_ranges", [])
        if not quote_ranges:
            return None

        cfg = self.profile.behaviors.quote
        if not cfg.enabled:
            return None

        for qr in quote_ranges:
            start = qr.get("start", -1)
            end = qr.get("end", -1)
            if start <= char_position < end:
                qtype = qr.get("type", "direct_quote")
                if qtype == "paraphrase_close":
                    return cfg.paraphrase_speed_multiplier
                return cfg.speed_multiplier

        return None

    # ------------------------------------------------------------------
    # Feature 12: Autocorrect fixes
    # ------------------------------------------------------------------

    def _track_autocorrect_words(self, run_text: str, actions: list[TypingAction]) -> None:
        """Defer verified, unique emitted words; AI offsets never select text."""
        cfg = self.profile.behaviors.autocorrect
        if not cfg.enabled or self._autocorrect_attempts >= cfg.max_per_session:
            return
        words = list(re.finditer(r"\b\w+\b", run_text))
        for pending in self._pending_autocorrects:
            pending["words_remaining"] -= len(words)
        for idx, match in enumerate(words):
            for fix in self._behavioral_content.get("autocorrect_fixes", []):
                word, correct = match.group(), fix.get("correct", "")
                if fix.get("word") == word and correct and correct != word:
                    if (not any(p["word"] == word for p in self._pending_autocorrects)
                            and self._rng.random() < cfg.probability_per_word):
                        self._pending_autocorrects.append({
                            "word": word, "correct": correct,
                            "words_remaining": self._rng.randint(cfg.min_words_back, cfg.max_words_back) - (len(words) - idx - 1),
                        })
                    break
        still_pending = []
        for pending in self._pending_autocorrects:
            if self._autocorrect_attempts >= cfg.max_per_session:
                break
            if pending["words_remaining"] > 0:
                still_pending.append(pending)
                continue
            # Rejected ambiguous or distant edits also consume work. Otherwise
            # repeated candidates replay and search every growing chunk prefix.
            self._autocorrect_attempts += 1
            state = PlannedText(self._chunk_prefix).apply(actions)
            edits = self._build_autocorrect_fix(
                pending["word"], pending["correct"],
                known_text=state.text if state.valid else "",
            )
            if edits and self._autocorrect_count < cfg.max_per_session:
                actions.extend(edits)
                self._autocorrect_count += 1
        self._pending_autocorrects = still_pending

    def _build_autocorrect_fix(
        self, wrong_word: str, correct_word: str, words_back: int = 0,
        *, known_text: str | None = None,
    ) -> list[TypingAction]:
        """Return to a verified word and then the exact insertion endpoint."""
        if known_text is None:
            return []
        matches = list(re.finditer(r"(?<!\w)" + re.escape(wrong_word) + r"(?!\w)", known_text))
        if len(matches) != 1:
            return []
        edits = replace_known_span(known_text, wrong_word, correct_word)
        if not edits:
            return []
        return [Pause(duration=self._r(self.profile.behaviors.autocorrect.notice_pause), description="Noticed a misspelled word"), *edits]

    # ------------------------------------------------------------------
    # Feature 13: Final proofreading pass
    # ------------------------------------------------------------------

    def _build_final_proofread(self, full_text: str) -> list[TypingAction]:
        """Apply only unique corrections in actual emitted text, then return."""
        cfg = self.profile.behaviors.final_proofread
        if not cfg.enabled or len(full_text) < cfg.min_text_length or self._rng.random() > cfg.probability:
            return []
        actions = []
        applied = 0
        for fix in self._behavioral_content.get("proofreading_fixes", []):
            if applied >= cfg.max_fixes:
                break
            edits = replace_known_span(full_text, fix.get("original", ""), fix.get("fixed", ""))
            if not edits:
                continue
            actions.append(Pause(duration=self._r(cfg.found_issue_pause), description="Found issue during proofreading"))
            actions.extend(edits)
            full_text = PlannedText(full_text).apply(edits).text
            applied += 1
        return actions

    # ------------------------------------------------------------------
    # Convenience: plan from plain text
    # ------------------------------------------------------------------

    def plan_plain_text(self, text: str) -> TypingPlan:
        """Create a plan from a single plain-text string (no formatting)."""
        segment = TextSegment(text=text)
        return self.plan([segment])
