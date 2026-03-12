"""
AI-powered typing plan generation using Claude.

Instead of randomly placing mistakes and pauses, Claude analyzes the text
and generates a human-realistic typing plan — where to pause to "think",
what kinds of mistakes make sense, where to rewrite sentences, and how
speed should vary based on content difficulty.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import anthropic
from dotenv import load_dotenv

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
    TypingProfile,
)
from .typing_planner import FORMAT_SHORTCUTS, FORMAT_TYPE_MAP, TypingPlanner

logger = logging.getLogger(__name__)

# Load API key from .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

SYSTEM_PROMPT = """\
You are a typing behavior analyst. Your job is to take text that someone wants to type \
and generate a realistic plan for how a human would actually type it — including natural \
pauses, mistakes, rewrites, and speed variations.

You understand human typing deeply:
- People type common words faster than uncommon ones
- People pause before difficult words, proper nouns, or technical terms
- People sometimes type a word wrong and fix it immediately
- People sometimes type part of a sentence, reconsider, delete back, and retype differently
- People take longer pauses at paragraph breaks and between ideas
- Typing speed varies — bursts of fast typing followed by slower, more thoughtful typing
- Fatigue builds over time, slightly slowing typing and increasing errors
- People occasionally pause to re-read what they just typed

Return your response as a JSON object with this exact structure:
{
  "segments": [
    {
      "text": "the actual text for this segment",
      "actions": [
        {"type": "type", "text": "the actual text"},
        {"type": "pause", "duration": 1.5, "reason": "thinking about next sentence"},
        {"type": "mistake", "wrong": "teh", "correct": "the", "chars_before_noticing": 2},
        {"type": "rewrite", "first_attempt": "this is kind of", "final_version": "this is essentially", "reason": "rephrasing for clarity"},
        {"type": "speed_change", "multiplier": 1.3, "reason": "common phrase, typing faster"},
        {"type": "speed_change", "multiplier": 0.7, "reason": "technical term, slowing down"}
      ]
    }
  ],
  "overall_strategy": "description of the typing approach",
  "estimated_minutes": 3.5
}

Rules:
- Break text into logical segments (sentences or phrases)
- CRITICAL: Preserve ALL whitespace exactly as it appears in the original text. Every space after periods, commas, and between words MUST be included in the "type" action text. Do NOT strip leading or trailing spaces from type actions.
- Place mistakes on realistic characters (adjacent keys, transpositions, double letters)
- Pauses should vary: 0.3-1.5s between sentences, 1-4s between paragraphs, 2-8s for "thinking"
- Rewrites should be natural — type a plausible but slightly worse version first, then fix it
- Speed multipliers: 0.5 = very slow/careful, 1.0 = normal, 1.5 = fast burst
- Don't overdo mistakes — real humans make typos on roughly 3-5% of words
- Make the typing feel ALIVE, not mechanical
- When splitting text across multiple type actions, the trailing space after punctuation MUST be included (e.g. "Hello. " not "Hello.")
"""


class AIPlanner:
    """Uses Claude to generate intelligent, realistic typing plans."""

    def __init__(self, settings: Settings | None = None, api_key: str | None = None):
        self.settings = settings or Settings()
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client: Optional[anthropic.Anthropic] = None
        self._fallback_planner = TypingPlanner(self.settings)
        self._enabled = bool(self._api_key)

        if self._api_key:
            try:
                self._client = anthropic.Anthropic(api_key=self._api_key)
                logger.info("AI Planner initialized with Claude API")
            except Exception:
                logger.exception("Failed to initialize Anthropic client")
                self._enabled = False
        else:
            logger.warning("No ANTHROPIC_API_KEY found — AI planner disabled, using fallback")

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback_planner = TypingPlanner(settings)

    def plan(self, segments: list[TextSegment]) -> TypingPlan:
        """Generate a typing plan using Claude AI, falling back to rule-based if needed."""
        if not self.is_enabled:
            logger.info("AI planner disabled, using rule-based fallback")
            return self._fallback_planner.plan(segments)

        try:
            return self._ai_plan(segments)
        except Exception:
            logger.exception("AI planning failed, falling back to rule-based planner")
            return self._fallback_planner.plan(segments)

    def _ai_plan(self, segments: list[TextSegment]) -> TypingPlan:
        """Call Claude to generate a typing plan."""
        # Build the prompt with the text and current settings
        text_parts = []
        for seg in segments:
            fmt_desc = []
            if seg.bold:
                fmt_desc.append("BOLD")
            if seg.italic:
                fmt_desc.append("ITALIC")
            if seg.underline:
                fmt_desc.append("UNDERLINE")
            if seg.heading_level:
                fmt_desc.append(f"H{seg.heading_level}")
            if seg.list_type:
                fmt_desc.append(f"LIST:{seg.list_type}")

            fmt_str = f" [{', '.join(fmt_desc)}]" if fmt_desc else ""
            text_parts.append(f"{seg.text}{fmt_str}")

        full_text = "\n".join(text_parts)
        word_count = sum(len(seg.text.split()) for seg in segments)

        user_prompt = f"""\
Here is the text to type ({word_count} words). Generate a realistic typing plan.

Current typing settings:
- Target WPM: {self.settings.wpm}
- Error rate: {self.settings.error_rate} (probability per word)
- Rewrite probability: {self.settings.rewrite_max_probability}
- Fatigue enabled: {self.settings.fatigue_enabled}
- Burst typing enabled: {self.settings.burst_typing_enabled}

Text to type:
---
{full_text}
---

Generate the typing plan as JSON. Make it feel like a real person typing this for the first time. \
Include {max(1, int(word_count * self.settings.error_rate))} typos and \
{max(0, int(word_count * self.settings.rewrite_max_probability))} rewrites spread naturally throughout."""

        logger.info("Requesting AI typing plan for %d words...", word_count)

        response = self._client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=120.0,
        )

        # Check if response was truncated — fall back immediately
        if response.stop_reason == "max_tokens":
            logger.warning("AI response truncated, falling back to rule-based planner")
            return self._fallback_planner.plan(segments)

        # Extract JSON from response
        if not response.content:
            logger.warning("Empty AI response, falling back")
            return self._fallback_planner.plan(segments)
        response_text = response.content[0].text
        plan_data = self._parse_json_response(response_text)

        if not plan_data:
            logger.warning("Could not parse AI response, falling back")
            return self._fallback_planner.plan(segments)

        # Convert AI plan to TypingPlan
        return self._convert_ai_plan(plan_data, segments)

    def _parse_json_response(self, text: str) -> Optional[dict]:
        """Extract and parse JSON from Claude's response."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block in markdown code fences
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object
        brace_start = text.find("{")
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start : i + 1])
                        except json.JSONDecodeError:
                            break

        logger.warning("Failed to parse JSON from AI response")
        return None

    def _convert_ai_plan(
        self, plan_data: dict, original_segments: list[TextSegment]
    ) -> TypingPlan:
        """Convert Claude's JSON plan into a TypingPlan with proper TypingActions."""
        actions: list[TypingAction] = []
        total_chars = 0

        # Build a map of formatting from original segments
        seg_formats = {seg.text.strip(): seg.formatting for seg in original_segments}

        ai_segments = plan_data.get("segments", [])

        for ai_seg in ai_segments:
            seg_text = ai_seg.get("text", "")
            seg_actions = ai_seg.get("actions", [])

            # Try to find matching formatting from original segments
            formatting = self._find_formatting(seg_text, seg_formats)

            # Apply formatting if needed
            if formatting:
                fmt_actions = self._build_formatting_actions(formatting)
                actions.extend(fmt_actions)

            # Process each action in the segment
            for act in seg_actions:
                act_type = act.get("type", "")
                new_actions, chars = self._convert_action(act)
                actions.extend(new_actions)
                total_chars += chars

            # Untoggle formatting
            if formatting:
                untoggle = self._build_untoggle_actions(formatting)
                actions.extend(untoggle)

        # Calculate estimated duration
        chars_per_sec = (self.settings.wpm * 5) / 60
        est_duration = total_chars / chars_per_sec if chars_per_sec > 0 else 0

        # Safety: fix missing spaces between consecutive TypeText actions
        # (Claude often drops trailing spaces when splitting sentences)
        actions = self._fix_missing_spaces(actions)

        # Recount chars after fix
        total_chars = sum(
            len(a.text) for a in actions if isinstance(a, TypeText)
        ) + sum(
            len(a.correct_text) for a in actions if isinstance(a, MakeMistake)
        ) + sum(
            len(a.new_text) for a in actions if isinstance(a, Rewrite)
        )

        return TypingPlan(
            actions=actions,
            total_characters=total_chars,
            estimated_duration_seconds=est_duration,
            segment_count=len(ai_segments),
            metadata={
                "ai_generated": True,
                "strategy": plan_data.get("overall_strategy", ""),
                "ai_estimated_minutes": plan_data.get("estimated_minutes", 0),
            },
        )

    def _convert_action(self, act: dict) -> tuple[list[TypingAction], int]:
        """Convert a single AI action dict to TypingAction(s)."""
        act_type = act.get("type", "")
        actions: list[TypingAction] = []
        chars = 0

        if act_type == "type":
            text = act.get("text", "")
            if text:
                # Split on newlines to insert PressKey(enter)
                parts = text.split("\n")
                for i, part in enumerate(parts):
                    if part:
                        actions.append(TypeText(text=part))
                        chars += len(part)
                    if i < len(parts) - 1:
                        actions.append(PressKey(key="enter"))
                        chars += 1

        elif act_type == "pause":
            duration = float(act.get("duration", 1.0))
            # Clamp to reasonable range
            duration = max(0.1, min(duration, 15.0))
            actions.append(Pause(duration=duration))

        elif act_type == "mistake":
            wrong = act.get("wrong", "")
            correct = act.get("correct", "")
            notice_after = int(act.get("chars_before_noticing", 0))
            if wrong and correct:
                actions.append(MakeMistake(
                    wrong_text=wrong,
                    correct_text=correct,
                    chars_before_noticing=notice_after,
                ))
                chars += len(correct)

        elif act_type == "rewrite":
            first_attempt = act.get("first_attempt", "")
            final_version = act.get("final_version", "")
            if first_attempt and final_version:
                # Type the first attempt
                actions.append(TypeText(text=first_attempt))
                # Pause to "re-read"
                actions.append(Pause(duration=1.0))
                # Delete it
                actions.append(Rewrite.simple(
                    delete_count=len(first_attempt),
                    text=final_version,
                ))
                chars += len(final_version)

        elif act_type == "speed_change":
            # Speed changes are handled implicitly through pause durations
            # We could add a micro-pause for slowdown
            multiplier = float(act.get("multiplier", 1.0))
            if multiplier < 0.8:
                # Slowing down — add a tiny thinking pause
                actions.append(Pause(duration=0.3))

        return actions, chars

    @staticmethod
    def _fix_missing_spaces(actions: list[TypingAction]) -> list[TypingAction]:
        """Fix missing spaces between consecutive TypeText actions.

        Claude often generates plans where "sentence." and "Next" are separate
        type actions with no space between them. This inserts the missing space.
        """
        fixed: list[TypingAction] = []
        for i, action in enumerate(actions):
            fixed.append(action)
            # Check if this TypeText ends without a space and the next TypeText
            # starts with a letter (missing space between sentences/words)
            if isinstance(action, TypeText) and action.text:
                # Find the next TypeText action (skip pauses etc.)
                next_type = None
                for j in range(i + 1, len(actions)):
                    if isinstance(actions[j], TypeText):
                        next_type = actions[j]
                        break
                    elif isinstance(actions[j], (MakeMistake,)):
                        # MakeMistake starts typing — check its wrong_text
                        break
                    elif isinstance(actions[j], (Pause,)):
                        continue
                    else:
                        break

                if next_type and next_type.text:
                    last_char = action.text[-1]
                    first_char = next_type.text[0]
                    # If current ends with punctuation or letter and next starts
                    # with a letter, and there's no space — add one
                    if (last_char in ".!?,;:" or last_char.isalnum()) and first_char.isalnum():
                        if not action.text[-1].isspace():
                            action.text += " "

        return fixed

    def _find_formatting(self, text: str, seg_formats: dict) -> dict:
        """Find the best matching formatting for a text segment."""
        text_stripped = text.strip()
        if text_stripped in seg_formats:
            return seg_formats[text_stripped]

        # Fuzzy match — find the segment whose text is contained in or contains this text
        for seg_text, fmt in seg_formats.items():
            if seg_text in text_stripped or text_stripped in seg_text:
                return fmt

        return {}

    def _build_formatting_actions(self, fmt: dict) -> list[TypingAction]:
        """Build formatting shortcut actions from a formatting dict."""
        actions: list[TypingAction] = []

        heading = fmt.get("heading_level", 0)
        if heading and 1 <= heading <= 6:
            key = f"heading_{heading}"
            if key in FORMAT_SHORTCUTS:
                actions.append(ApplyFormatting(
                    format_type=FORMAT_TYPE_MAP[key],
                    shortcut=FORMAT_SHORTCUTS[key],
                ))

        list_type = fmt.get("list_type")
        if list_type in ("numbered", "numbered_list", "ordered"):
            actions.append(ApplyFormatting(
                format_type=FormatType.NUMBERED_LIST,
                shortcut=FORMAT_SHORTCUTS["numbered_list"],
            ))
        elif list_type in ("bulleted", "bulleted_list", "bullet", "unordered"):
            actions.append(ApplyFormatting(
                format_type=FormatType.BULLETED_LIST,
                shortcut=FORMAT_SHORTCUTS["bulleted_list"],
            ))

        alignment = fmt.get("alignment")
        if alignment:
            align_key = f"align_{alignment}"
            if align_key in FORMAT_SHORTCUTS:
                actions.append(ApplyFormatting(
                    format_type=FORMAT_TYPE_MAP[align_key],
                    shortcut=FORMAT_SHORTCUTS[align_key],
                ))

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

    def _build_untoggle_actions(self, fmt: dict) -> list[TypingAction]:
        """Build actions to turn off toggle formatting."""
        actions: list[TypingAction] = []
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


class AIRewriter:
    """Uses Claude to generate plausible 'first draft' versions of text
    that a human might type before deleting and rewriting better."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client: Optional[anthropic.Anthropic] = None
        self._enabled = bool(self._api_key)
        self._cache: dict[str, str] = {}  # final_text -> draft_text

        if self._api_key:
            try:
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except Exception:
                self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    def generate_first_draft(self, final_text: str, context: str = "") -> Optional[str]:
        """Generate a plausible worse first attempt of a text span.

        Args:
            final_text: The final/correct version of the text.
            context: Surrounding text for context.

        Returns:
            A plausible first-draft version, or None if AI is unavailable.
        """
        if not self.is_enabled:
            return None

        # Check cache
        if final_text in self._cache:
            return self._cache[final_text]

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=30.0,
                max_tokens=400,
                system=(
                    "You generate plausible first-draft versions of text. "
                    "Given a final polished version, return a slightly rougher version "
                    "that someone might type first before editing. Make it slightly "
                    "wordier, less precise, or with different word choices. "
                    "Keep approximately the same length. "
                    "Return ONLY the draft text, nothing else."
                ),
                messages=[{
                    "role": "user",
                    "content": f"Final version: {final_text}\nContext: {context}\n\nFirst draft:",
                }],
            )
            draft = response.content[0].text.strip()
            # Sanity check — draft should be similar length
            if 0.3 < len(draft) / max(len(final_text), 1) < 2.5:
                self._cache[final_text] = draft
                return draft
            return None
        except Exception:
            logger.exception("AI rewriter failed")
            return None

    def generate_drafts_batch(
        self, spans: list[dict[str, str]]
    ) -> list[Optional[str]]:
        """Generate rough drafts for multiple text spans in a single API call.

        Args:
            spans: List of dicts with 'text' and optional 'context' keys.

        Returns:
            List of draft strings (or None for failures), same length as input.
        """
        if not self.is_enabled or not spans:
            return [None] * len(spans)

        # Check cache for already-generated drafts
        results: list[Optional[str]] = [None] * len(spans)
        uncached_indices: list[int] = []
        uncached_spans: list[dict[str, str]] = []

        for i, span in enumerate(spans):
            text = span.get("text", "")
            if text in self._cache:
                results[i] = self._cache[text]
            else:
                uncached_indices.append(i)
                uncached_spans.append(span)

        if not uncached_spans:
            return results

        # Build batch prompt
        prompt_parts = []
        for idx, span in enumerate(uncached_spans):
            text = span.get("text", "")
            context = span.get("context", "")
            prompt_parts.append(
                f"[{idx}] Final: {text}"
                + (f"\n    Context: {context}" if context else "")
            )

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=60.0,
                max_tokens=4096,
                system=(
                    "You generate plausible first-draft versions of text spans. "
                    "Given multiple final/polished versions, return a rougher version of each "
                    "that someone might type first before editing. Make each slightly "
                    "wordier, less precise, or with different word choices. "
                    "Keep approximately the same length as each original. "
                    "Return a JSON array of strings, one draft per input, in the same order. "
                    "Return ONLY the JSON array, nothing else."
                ),
                messages=[{
                    "role": "user",
                    "content": "Generate rough first-draft versions:\n\n"
                    + "\n".join(prompt_parts),
                }],
            )

            response_text = response.content[0].text.strip()

            # Parse JSON array
            drafts = json.loads(response_text)
            if not isinstance(drafts, list):
                return results

            for i, draft in enumerate(drafts):
                if i >= len(uncached_indices):
                    break
                orig_idx = uncached_indices[i]
                orig_text = uncached_spans[i].get("text", "")
                if (
                    isinstance(draft, str)
                    and draft
                    and 0.3 < len(draft) / max(len(orig_text), 1) < 2.5
                ):
                    results[orig_idx] = draft
                    self._cache[orig_text] = draft

        except Exception:
            logger.exception("AI batch rewriter failed")

        return results

    def pick_revisit_targets(
        self, typed_so_far: str, num_targets: int = 3
    ) -> list[dict]:
        """Ask AI to pick phrases/sentences from already-typed text that a teen
        would go back and revise while writing later paragraphs.

        Returns list of dicts with:
            - 'original': the exact text to find and replace
            - 'revised': what to replace it with
            - 'reason': why the teen would change it (for logging)
        """
        if not self.is_enabled or not typed_so_far or len(typed_so_far) < 50:
            return []

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=30.0,
                max_tokens=2048,
                system=(
                    "You are simulating a 16-year-old student who, while typing an essay, "
                    "occasionally scrolls back up to revise something they wrote earlier. "
                    "Given text already typed, pick 1-3 short phrases or sentences the teen "
                    "would go back and change — maybe rewording something awkward, fixing a "
                    "word choice, strengthening an argument, or changing their mind about "
                    "how they said something.\n\n"
                    "Return a JSON array of objects:\n"
                    "[\n"
                    '  {"original": "exact text from the input", '
                    '"revised": "what they change it to", '
                    '"reason": "why they changed it"}\n'
                    "]\n\n"
                    "RULES:\n"
                    "- 'original' must be an EXACT substring of the input text\n"
                    "- 'revised' should be similar length (not drastically different)\n"
                    "- Keep changes small and natural — a word or two, maybe a short phrase\n"
                    "- Don't change everything — just 1-3 small edits\n"
                    "- Return ONLY the JSON array"
                ),
                messages=[{
                    "role": "user",
                    "content": f"Text typed so far:\n---\n{typed_so_far}\n---\n\n"
                    f"Pick up to {num_targets} things to revise:",
                }],
            )

            response_text = response.content[0].text.strip()
            targets = json.loads(response_text)
            if not isinstance(targets, list):
                return []

            valid_targets = []
            for t in targets:
                original = t.get("original", "")
                revised = t.get("revised", "")
                if (
                    original
                    and revised
                    and original != revised
                    and original in typed_so_far
                    and 0.3 < len(revised) / max(len(original), 1) < 3.0
                ):
                    valid_targets.append(t)

            return valid_targets[:num_targets]

        except Exception:
            logger.exception("AI revisit target picker failed")
            return []

    def clear_cache(self) -> None:
        """Clear the draft cache (e.g. between typing sessions)."""
        self._cache.clear()


# ---------------------------------------------------------------------------
# AI Profile Generator — generates a unique TypingProfile per session
# ---------------------------------------------------------------------------

PROFILE_SYSTEM_PROMPT = """\
You generate unique behavioral fingerprints for a typing simulation of a 16-year-old \
keyboard peeker. Given the text they will type, produce a complete set of timing parameters \
that vary meaningfully from session to session. Consider:
- Text difficulty (academic vs casual, familiar vs unfamiliar vocabulary)
- Text length (longer text = more fatigue, more distractions)
- The teen's "mood" this session (energetic vs tired vs distracted)
- Content familiarity (an essay about their hobby vs a science report)

Every session MUST be unique — vary the parameters randomly even for identical text. \
Do NOT return the same profile twice.

Return a JSON object matching this schema (all fields optional — omitted fields keep defaults):
{
  "persona_description": "string describing this session's typist mood",
  "confidence_level": 0.0-1.0,
  "familiarity_with_content": 0.0-1.0,
  "energy_level": 0.0-1.0,
  "keystroke": {
    "shift_multiplier": {"min": 1.2, "max": 2.0},
    "end_punctuation_multiplier": {"min": 1.1, "max": 1.5},
    "mid_punctuation_multiplier": {"min": 1.1, "max": 1.4},
    "digit_multiplier": {"min": 1.3, "max": 2.2},
    "symbol_multiplier": {"min": 1.2, "max": 1.8},
    "hunt_key_multiplier": {"min": 1.1, "max": 1.5},
    "jitter_sigma": 0.15-0.50,
    "warmup_chars": 5-30,
    "warmup_slowdown": 0.05-0.40,
    "first_char_of_word_multiplier": {"min": 1.0, "max": 1.5},
    "early_word_multiplier": {"min": 0.90, "max": 1.15},
    "mid_word_multiplier": {"min": 0.82, "max": 1.0},
    "fast_digraph_multiplier": {"min": 0.82, "max": 0.98},
    "slow_digraph_multiplier": {"min": 1.05, "max": 1.30},
    "common_word_short_multiplier": {"min": 0.75, "max": 0.95},
    "common_word_long_multiplier": {"min": 0.88, "max": 1.0},
    "common_double_multiplier": {"min": 0.80, "max": 0.98},
    "uncommon_double_multiplier": {"min": 0.90, "max": 1.15},
    "space_normal_multiplier": {"min": 0.9, "max": 1.5},
    "space_thinking_multiplier": {"min": 1.5, "max": 4.0},
    "space_thinking_probability": 0.5-0.85,
    "enter_multiplier": {"min": 1.2, "max": 2.5},
    "post_error_multiplier": {"min": 1.05, "max": 1.50},
    "delay_clamp_min": 0.025-0.050,
    "delay_clamp_max": 1.5-3.0,
    "bimodal_fast_probability": 0.50-0.80,
    "bimodal_fast_sigma": 0.12-0.25,
    "bimodal_slow_sigma": 0.35-0.55,
    "bimodal_slow_multiplier": 1.15-1.60,
    "finger_index_multiplier": 0.85-0.98,
    "finger_middle_multiplier": 0.90-1.02,
    "finger_ring_multiplier": 1.02-1.15,
    "finger_pinky_multiplier": 1.10-1.30,
    "hand_alternation_multiplier": 0.85-0.95,
    "same_hand_multiplier": 1.02-1.12,
    "same_finger_multiplier": 1.12-1.30,
    "syllable_pause_multiplier": {"min": 1.03, "max": 1.25}
  },
  "keys": {
    "hunt_keys": ["z","x","q","j","k","v"],
    "common_doubles": ["l","s","e","t","r","o","p","n"],
    "text_specific_easy_words": ["words","from","this","text","the","teen","knows","well"],
    "text_specific_hard_words": ["words","from","this","text","that","are","unfamiliar"]
  },
  "peek": {
    "min_chars_before_peek": 8-20,
    "probability_factor_per_char": 0.02-0.08,
    "max_probability": 0.3-0.7,
    "pause_duration": {"min": 0.3, "max": 1.5}
  },
  "mistakes": {
    "type_weights": {"adjacent": 40-65, "transpose_skip": 10-25, "double": 5-20, "wrong_shift": 5-15, "drop": 3-12},
    "unnoticed_rate": 0.03-0.15,
    "immediate_notice_rate": 0.25-0.55,
    "fatigue_error_boost": 0.02-0.08,
    "burst_error_multiplier": 1.2-2.0
  },
  "pauses": {
    "thought_pause_sentences_interval": {"min": 1, "max": 5},
    "thought_pause_duration": {"min": 1.5, "max": 8.0},
    "thinking_pause_probability_factor": 0.05-0.20
  },
  "burst": {
    "base_probability": 0.01-0.05,
    "post_pause_probability": 0.05-0.20
  },
  "fatigue": {
    "burst_fatigue_multiplier": 1.2-2.0,
    "recovery_probability": 0.01-0.05,
    "max_level": 0.2-0.6,
    "pause_recovery_rate": 0.002-0.010,
    "backspace_miss_base_rate": 0.01-0.05,
    "backspace_miss_fatigue_scale": 0.08-0.25
  },
  "correction": {
    "slow_correction_split": 0.3-0.7,
    "slow_correction_fast_pause": {"min": 0.15, "max": 0.60},
    "slow_correction_slow_pause": {"min": 0.40, "max": 1.50},
    "fast_loop_probability": 0.20-0.50,
    "fast_loop_pause": {"min": 0.06, "max": 0.25},
    "slow_loop_search_pause": {"min": 0.20, "max": 0.90}
  },
  "rewrite": {
    "word_pause": {"min": 0.5, "max": 2.5},
    "sentence_pause": {"min": 0.8, "max": 3.0},
    "paragraph_pause": {"min": 1.0, "max": 4.0},
    "cascade_max_depth": 1-3,
    "deep_level_density_reduction": 0.3-0.7
  },
  "proofread": {
    "re_reading_pause": {"min": 1.0, "max": 4.0},
    "found_typo_pause": {"min": 0.2, "max": 1.0},
    "revisit_re_reading_pause": {"min": 1.5, "max": 6.0}
  },
  "orchestration": {
    "formatting_hotkey_pause": 0.05-0.20,
    "navigation_hotkey_pause": {"min": 0.03, "max": 0.12},
    "arrow_key_pause": {"min": 0.02, "max": 0.08}
  },
  "behaviors": {
    "distraction": {
      "probability_per_break_point": 0.01-0.08,
      "short_weight": 0.3-0.6,
      "medium_weight": 0.2-0.4,
      "long_weight": 0.05-0.25,
      "very_long_weight": 0.02-0.10
    },
    "abandonment": {
      "probability_per_word": 0.01-0.05,
      "max_per_session": 1-5
    },
    "restructuring": {
      "probability_per_sentence": 0.02-0.08,
      "max_per_session": 1-3
    },
    "formatting_hesitation": {
      "wrong_shortcut_probability": 0.05-0.30,
      "familiarity_ratings": {"bold": 0.7-1.0, "italic": 0.6-0.9, "heading_1": 0.1-0.5}
    },
    "quote": {
      "speed_multiplier": 0.4-0.7,
      "source_glance_frequency": 0.04-0.15,
      "misread_rate": 0.02-0.08
    },
    "autocorrect": {
      "probability_per_word": 0.04-0.12,
      "max_per_session": 2-6
    },
    "final_proofread": {
      "probability": 0.3-0.8,
      "max_fixes": 2-6
    },
    "pre_word_pause": {
      "difficulty_threshold": 0.3-0.6,
      "base_pause": {"min": 0.08, "max": 0.35},
      "hard_word_pause": {"min": 0.20, "max": 0.70},
      "very_hard_word_pause": {"min": 0.40, "max": 1.40}
    },
    "composition_mode": {
      "clause_pause": {"min": 0.6, "max": 3.0},
      "sentence_composition_pause": {"min": 1.0, "max": 5.0},
      "composition_speed_multiplier": 0.70-0.90,
      "copy_typing_speed_multiplier": 1.05-1.20
    }
  }
}

IMPORTANT: Vary values meaningfully. A tired teen has higher jitter, more mistakes, longer \
pauses. An energetic teen has lower jitter, faster typing, fewer distractions. A teen \
unfamiliar with the content has more hard words, more rewrites, slower speed. \
Return ONLY the JSON object.\
"""

BEHAVIORAL_SYSTEM_PROMPT = """\
You generate specific typing behaviors for a 16-year-old student typing an essay. \
Given the text, produce content-specific behaviors: which words to abandon, sentences \
to restructure, where distractions happen, what quotes to slow down for, syllable \
breakdowns for difficult words, word difficulty ratings, and composition mode annotations.

Return a JSON object:
{
  "word_abandonments": [
    {"word": "approximately", "position": 234, "abandon_after_chars": 6, "replacement": "about"}
  ],
  "sentence_restructures": [
    {"original_sentence": "exact sentence from text", "first_draft": "wordier version teen types first"}
  ],
  "distraction_points": [
    {"position": 450, "quality": "high"}
  ],
  "quote_ranges": [
    {"start": 100, "end": 200, "type": "direct_quote"}
  ],
  "autocorrect_fixes": [
    {"word": "recieve", "correct": "receive", "position": 300}
  ],
  "proofreading_fixes": [
    {"original": "there paper", "fixed": "their paper", "position_fraction": 0.3}
  ],
  "word_speed_map": [
    {"word": "photosynthesis", "multiplier": 1.4, "capital_difficulty": 0.0},
    {"word": "the", "multiplier": 0.8, "capital_difficulty": 0.0}
  ],
  "word_difficulty_ratings": [
    {"word": "photosynthesis", "difficulty": 0.9},
    {"word": "approximately", "difficulty": 0.7},
    {"word": "the", "difficulty": 0.0}
  ],
  "syllable_boundaries": [
    {"word": "photosynthesis", "syllables": ["pho", "to", "syn", "the", "sis"]},
    {"word": "approximately", "syllables": ["ap", "prox", "i", "mate", "ly"]}
  ],
  "composition_annotations": [
    {"start": 0, "end": 150, "mode": "composition", "reason": "original argument"},
    {"start": 151, "end": 300, "mode": "copy", "reason": "quoting source material"},
    {"start": 301, "end": 500, "mode": "composition", "reason": "analysis paragraph"}
  ]
}

RULES:
- word_abandonments: Pick 1-4 longer/uncommon words. abandon_after_chars must be >= 3 \
and < word length. replacement must be a simpler synonym.
- sentence_restructures: Pick 0-2 sentences. first_draft is a wordier/more awkward \
version the teen types first before deleting and typing the real version.
- distraction_points: Pick 2-5 natural break points (paragraph boundaries, after \
complex thoughts). quality is "high" (paragraph break), "medium" (sentence end), \
or "low" (phrase boundary). position is char offset.
- quote_ranges: Identify text in quotation marks or cited passages. type is \
"direct_quote", "block_quote", or "paraphrase_close".
- autocorrect_fixes: Pick 2-4 words a teen would commonly misspell, then later \
arrow back to fix. position is approximate char offset.
- proofreading_fixes: Pick 1-3 small errors to fix in a final read-through. \
position_fraction is 0.0-1.0 (position in document as fraction).
- word_speed_map: List 15-30 words with speed multipliers. <1.0 = faster (familiar), \
>1.0 = slower (unfamiliar). Include capital_difficulty 0.0-1.0 for capitalized words.
- word_difficulty_ratings: Rate 10-20 words from the text on difficulty 0.0-1.0. \
Include hard words (technical, uncommon, long) with high difficulty and common words \
with low difficulty. A teen pauses before typing difficult words.
- syllable_boundaries: Break down 10-15 difficult or multi-syllable words into syllables. \
Each syllable is a substring; concatenated they must equal the full word. \
A teen types slightly slower at syllable boundaries within unfamiliar words.
- composition_annotations: Divide the text into zones of "composition" (the teen is \
thinking up what to write — slower, more pauses at clause boundaries) vs "copy" \
(transcribing known content like quotes or factual statements — faster, fewer pauses). \
Mark 2-5 zones. start/end are char offsets. Most essay text is "composition".
- All positions and original texts must correspond to the actual input text.
- Return ONLY the JSON object.\
"""


class AIProfileGenerator:
    """Generates unique TypingProfile per session via Claude Haiku."""

    def __init__(self, settings: Settings | None = None, api_key: str | None = None) -> None:
        self.settings = settings or Settings()
        self._client: anthropic.Anthropic | None = None
        self._enabled = False

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if resolved_key:
            try:
                self._client = anthropic.Anthropic(api_key=resolved_key)
                self._enabled = True
            except Exception:
                self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    def generate_profile(self, text: str) -> TypingProfile:
        """Generate a unique TypingProfile for this text and session.

        Falls back to TypingProfile.defaults() on any failure.
        """
        if not self.is_enabled:
            return TypingProfile.defaults()

        import hashlib
        import time as _time
        # Random seed to ensure variation even with identical text
        seed = hashlib.md5(f"{text[:500]}{_time.time()}".encode()).hexdigest()[:8]

        # Compute text metadata
        words = text.split()
        word_count = len(words)
        avg_word_len = sum(len(w) for w in words) / max(word_count, 1)
        para_count = text.count("\n\n") + 1

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=30.0,
                max_tokens=3000,
                system=PROFILE_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate a unique typing profile for this session.\n\n"
                        f"Session seed: {seed}\n"
                        f"Text length: {len(text)} chars, {word_count} words, {para_count} paragraphs\n"
                        f"Average word length: {avg_word_len:.1f}\n"
                        f"User WPM setting: {self.settings.wpm}\n"
                        f"User error rate: {self.settings.error_rate}\n\n"
                        f"Text preview (first 1500 chars):\n---\n{text[:1500]}\n---"
                    ),
                }],
            )

            response_text = response.content[0].text.strip()
            # Strip markdown fences if present
            if response_text.startswith("```"):
                response_text = re.sub(r"^```\w*\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            data = json.loads(response_text)
            if isinstance(data, dict):
                profile = TypingProfile.from_dict(data)
                logger.info("Generated AI typing profile: %s", profile.persona_description)
                return profile

        except json.JSONDecodeError:
            logger.warning("AI profile response was not valid JSON, using defaults")
        except Exception:
            logger.exception("AI profile generation failed, using defaults")

        return TypingProfile.defaults()

    def generate_behavioral_content(self, text: str) -> dict[str, Any]:
        """Generate content-specific behaviors (abandonments, restructures, etc.).

        Returns a dict with behavioral data, or empty dict on failure.
        """
        if not self.is_enabled:
            return {}

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=45.0,
                max_tokens=4096,
                system=BEHAVIORAL_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate typing behaviors for this text:\n---\n{text[:3000]}\n---"
                    ),
                }],
            )

            response_text = response.content[0].text.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r"^```\w*\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            data = json.loads(response_text)
            if isinstance(data, dict):
                logger.info("Generated AI behavioral content: %d keys", len(data))
                return data

        except json.JSONDecodeError:
            logger.warning("AI behavioral content was not valid JSON")
        except Exception:
            logger.exception("AI behavioral content generation failed")

        return {}
