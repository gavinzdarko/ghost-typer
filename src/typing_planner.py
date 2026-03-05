"""Typing planner — converts formatted text segments into a TypingPlan.

Knows Google Docs keyboard shortcuts and builds a realistic sequence
of TypingActions, pre-planning mistakes, pauses, and rewrites.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .models import (
    ApplyFormatting,
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
)
from .human_errors import HumanErrors
from .word_alternatives import generate_rough_draft
from .typing_engine import TypingEngine

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


class TypingPlanner:
    """Converts TextSegments into a TypingPlan with realistic mistakes and pauses."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.engine = TypingEngine(self.settings)
        self._rng = random.Random()
        self._human_errors = HumanErrors(
            misspelling_rate=self.settings.error_rate,
            grammar_error_rate=getattr(self.settings, 'grammar_error_rate', 0.15),
            punctuation_error_rate=getattr(self.settings, 'punctuation_error_rate', 0.2),
        )

    def seed(self, value: int) -> None:
        self._rng.seed(value)
        self.engine.seed(value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(self, segments: list[TextSegment]) -> TypingPlan:
        """Build a complete TypingPlan from a list of TextSegments."""
        actions: list[TypingAction] = []
        total_chars = 0

        for seg_idx, segment in enumerate(segments):
            seg_actions, seg_chars = self._plan_segment(segment, seg_idx, len(segments))
            actions.extend(seg_actions)
            total_chars += seg_chars

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
        self, segment: TextSegment, seg_idx: int, total_segments: int
    ) -> tuple[list[TypingAction], int]:
        """Plan actions for a single TextSegment. Returns (actions, char_count)."""
        actions: list[TypingAction] = []
        char_count = 0

        # --- Skip all formatting — type as plain text so it inherits destination style ---

        # --- Apply human errors (grammar, punctuation, spelling that stay in) ---
        if self.settings.grammar_error_rate > 0 or self.settings.punctuation_error_rate > 0:
            modified_text, misspellings = self._human_errors.process_text(segment.text)
            # Build lookup for misspellings: word -> (wrong, correct)
            misspell_by_word = {}
            for wrong, correct, _pos in misspellings:
                misspell_by_word[correct.lower()] = (wrong, correct)
        else:
            modified_text = segment.text
            misspell_by_word = {}

        # --- Break text into typeable chunks ---
        chunks = self._break_into_chunks(modified_text)

        for chunk in chunks:
            chunk_actions, chunk_chars = self._plan_chunk(chunk, misspell_by_word=misspell_by_word)
            actions.extend(chunk_actions)
            char_count += chunk_chars

        # --- No formatting to untoggle (plain text mode) ---

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
            actions.append(ApplyFormatting(
                format_type=FORMAT_TYPE_MAP[key],
                shortcut=FORMAT_SHORTCUTS[key],
            ))

        # List type
        list_type = fmt.get("list_type")
        if list_type in ("numbered", "numbered_list"):
            actions.append(ApplyFormatting(
                format_type=FormatType.NUMBERED_LIST,
                shortcut=FORMAT_SHORTCUTS["numbered_list"],
            ))
        elif list_type in ("bulleted", "bulleted_list", "bullet"):
            actions.append(ApplyFormatting(
                format_type=FormatType.BULLETED_LIST,
                shortcut=FORMAT_SHORTCUTS["bulleted_list"],
            ))

        # Alignment
        alignment = fmt.get("alignment")
        if alignment:
            align_key = f"align_{alignment}"
            if align_key in FORMAT_SHORTCUTS:
                actions.append(ApplyFormatting(
                    format_type=FORMAT_TYPE_MAP[align_key],
                    shortcut=FORMAT_SHORTCUTS[align_key],
                ))

        # Bold / italic / underline (toggle ON)
        if fmt.get("bold"):
            actions.append(ApplyFormatting(
                format_type=FormatType.BOLD,
                shortcut=FORMAT_SHORTCUTS["bold"],
            ))
        if fmt.get("italic"):
            actions.append(ApplyFormatting(
                format_type=FormatType.ITALIC,
                shortcut=FORMAT_SHORTCUTS["italic"],
            ))
        if fmt.get("underline"):
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

    def _break_into_chunks(self, text: str) -> list[_Chunk]:
        """Split text into sentence / phrase / paragraph chunks."""
        chunks: list[_Chunk] = []

        # Split on paragraph boundaries (double newline or single newline)
        paragraphs = re.split(r"\n\n+", text)

        for p_idx, para in enumerate(paragraphs):
            is_last_para = p_idx == len(paragraphs) - 1
            if not para.strip():
                continue

            # Split paragraph into sentences
            sentences = SENTENCE_RE.split(para)

            for s_idx, sentence in enumerate(sentences):
                if not sentence.strip():
                    continue

                is_last_sentence = s_idx == len(sentences) - 1

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
                    ))

            # Add paragraph break (newline) unless it's the last paragraph
            if not is_last_para:
                chunks.append(_Chunk(text="\n", is_paragraph_end=True))

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
        self, chunk: _Chunk, misspell_by_word: dict[str, tuple[str, str]] | None = None
    ) -> tuple[list[TypingAction], int]:
        """Plan actions for a single chunk of text. Returns (actions, char_count)."""
        actions: list[TypingAction] = []
        text = chunk.text
        char_count = 0
        misspell_by_word = misspell_by_word or {}

        # Special case: newline
        if text == "\n":
            actions.append(PressKey(key="enter"))
            char_count += 1
            actions.append(Pause(duration=self.engine.paragraph_pause_duration()))
            return actions, char_count

        # --- Find word positions for misspelling corrections ---
        # Match by word content (not position) so it works across chunk boundaries.
        # pop() each match so the same word is only misspelled once.
        word_misspells: dict[int, tuple[str, str, int]] = {}  # chunk-local pos -> (wrong, correct, length)
        for match in re.finditer(r"\b(\w+)\b", text):
            word = match.group(1)
            lower = word.lower()
            if lower in misspell_by_word:
                wrong, correct = misspell_by_word.pop(lower)
                word_misspells[match.start()] = (wrong, correct, len(word))

        # --- Pre-scan for single-char mistake positions (adjacent key misclicks) ---
        mistake_positions = self._pick_mistake_positions(text)
        rewrite_position = self._pick_rewrite_position(text)

        i = 0
        while i < len(text):
            # Check for rewrite at this word boundary
            if rewrite_position is not None and i == rewrite_position:
                rewrite_actions, rewrite_chars, skip = self._build_rewrite(text, i)
                actions.extend(rewrite_actions)
                char_count += rewrite_chars
                i += skip
                rewrite_position = None
                continue

            # Check for whole-word misspelling at this position
            if i in word_misspells:
                wrong, correct, word_len = word_misspells[i]
                misspell_actions = self._build_word_misspelling(wrong, correct)
                actions.extend(misspell_actions)
                char_count += len(correct)
                i += word_len
                continue

            # Check for single-char mistake (adjacent key misclick)
            if i in mistake_positions:
                mistake_actions, mistake_chars = self._build_mistake(text, i)
                actions.extend(mistake_actions)
                char_count += mistake_chars
                i += mistake_chars
                continue

            # Random thinking pause mid-chunk
            if self.engine.should_thinking_pause() and i > 0 and text[i] == " ":
                actions.append(Pause(duration=self.engine.thinking_pause_duration()))

            # Normal typing — accumulate a run of non-mistake characters
            run_start = i
            while (
                i < len(text)
                and i not in mistake_positions
                and i != rewrite_position
                and i not in word_misspells
            ):
                i += 1
            run_text = text[run_start:i]
            if run_text:
                actions.append(TypeText(text=run_text))
                char_count += len(run_text)

                # Research: 35-44% of backspace presses are false alarms.
                # Occasionally backspace correct text then retype it.
                if len(run_text) >= 3 and self.engine.should_false_alarm():
                    fa_chars = min(self.engine.false_alarm_chars(), len(run_text))
                    deleted_text = run_text[-fa_chars:]
                    actions.append(Pause(duration=self._rng.uniform(0.2, 0.5)))
                    actions.append(Rewrite(
                        delete_count=fa_chars,
                        new_text=deleted_text,
                        description=f"False alarm: delete {fa_chars} correct chars, retype",
                    ))

        # --- Post-chunk pauses ---
        if chunk.is_sentence_end:
            actions.append(Pause(duration=self.engine.sentence_pause_duration()))
        if chunk.is_paragraph_end:
            actions.append(Pause(duration=self.engine.paragraph_pause_duration()))

        return actions, char_count

    # ------------------------------------------------------------------
    # Word-level misspelling (type wrong word, notice, fix)
    # ------------------------------------------------------------------

    def _build_word_misspelling(
        self, wrong: str, correct: str
    ) -> list[TypingAction]:
        """Type a misspelled word, pause as if noticing, backspace it, type correctly."""
        actions: list[TypingAction] = []

        # Type the wrong word
        actions.append(TypeText(text=wrong))

        # Sometimes notice immediately, sometimes type a space first then notice
        if self._rng.random() < 0.4:
            # Type the space after the word, then notice
            actions.append(TypeText(text=" "))
            actions.append(Pause(duration=self._rng.uniform(0.3, 0.8)))
            # Backspace the space + wrong word
            actions.append(Rewrite(
                delete_count=len(wrong) + 1,
                new_text=correct + " ",
            ))
        else:
            # Notice right at the end of the word
            actions.append(Pause(duration=self._rng.uniform(0.2, 0.6)))
            # Backspace the wrong word
            actions.append(Rewrite(
                delete_count=len(wrong),
                new_text=correct,
            ))

        return actions

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

    def _build_mistake(self, text: str, pos: int) -> tuple[list[TypingAction], int]:
        """Build actions for a single typo at position `pos`."""
        actions: list[TypingAction] = []
        intended_char = text[pos]
        typo_char = self.engine.generate_typo(intended_char)

        if typo_char == intended_char or not typo_char:
            # Couldn't generate a good typo — just type normally
            actions.append(TypeText(text=intended_char))
            return actions, 1

        # ~25% of typos go unnoticed — bad typist doesn't catch many errors
        # (peeker is looking at keyboard, not screen)
        if self._rng.random() < 0.25:
            actions.append(TypeText(text=typo_char))
            return actions, 1

        # ~70% get noticed and corrected
        chars_after = self.engine.chars_before_noticing_mistake()
        # Gather the extra chars typed before noticing (from text after pos)
        extra_text = text[pos + 1: pos + 1 + chars_after]

        wrong_text = typo_char + extra_text
        correct_text = intended_char + extra_text

        actions.append(MakeMistake(
            wrong_text=wrong_text,
            correct_text=correct_text,
            chars_before_noticing=len(extra_text),
        ))

        # The MakeMistake action consumes the intended char AND the extra chars
        # (they are typed as part of wrong_text, then backspaced and retyped in correct_text).
        return actions, 1 + len(extra_text)

    def _pick_rewrite_position(self, text: str) -> int | None:
        """Maybe choose a word boundary position for a rewrite action."""
        if not self.engine.should_rewrite():
            return None

        # Find word boundary positions
        word_starts: list[int] = []
        for m in re.finditer(r"\b\w", text):
            pos = m.start()
            if pos > 5:  # need some text before the rewrite point
                word_starts.append(pos)

        if not word_starts:
            return None

        return self._rng.choice(word_starts)

    def _build_rewrite(
        self, text: str, pos: int
    ) -> tuple[list[TypingAction], int, int]:
        """Build a rewrite action: type a rough/alternate version first, then
        delete it and type the real text (like a human drafting then revising).

        Returns (actions, char_count_of_new_text, chars_to_skip_in_original).
        """
        actions: list[TypingAction] = []

        # Figure out how many words to rewrite
        word_count = self.engine.rewrite_word_count()

        # Find `word_count` words starting at pos, preserving original spacing
        remaining = text[pos:]
        match = re.match(r"(?:\s*\S+){1," + str(word_count) + r"}", remaining)
        if not match:
            return [], 0, 0

        original_span = match.group(0)
        leading_ws = original_span[: len(original_span) - len(original_span.lstrip())]
        final_text = original_span.lstrip()

        if not final_text:
            return [], 0, 0

        # Type any leading whitespace before the rewrite so it's not silently dropped
        if leading_ws:
            actions.append(TypeText(text=leading_ws))

        # Generate an alternate "rough draft" version of the phrase
        draft_text = generate_rough_draft(final_text, self._rng)

        # If we couldn't produce a different version, skip the rewrite entirely
        if draft_text == final_text:
            return [], 0, 0

        # Type the rough draft first
        actions.append(TypeText(text=draft_text))

        # Pause as if re-reading and reconsidering
        actions.append(Pause(duration=self._rng.uniform(0.8, 2.0)))

        # Delete the draft and type the real text
        actions.append(Rewrite(
            delete_count=len(draft_text),
            new_text=final_text,
        ))

        # Skip the exact span in the original text
        chars_to_skip = len(original_span)
        chars_to_skip = min(chars_to_skip, len(text) - pos)

        return actions, len(final_text), chars_to_skip

    # ------------------------------------------------------------------
    # Convenience: plan from plain text
    # ------------------------------------------------------------------

    def plan_plain_text(self, text: str) -> TypingPlan:
        """Create a plan from a single plain-text string (no formatting)."""
        segment = TextSegment(text=text)
        return self.plan([segment])
