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
- Place mistakes on realistic characters (adjacent keys, transpositions, double letters)
- Pauses should vary: 0.3-1.5s between sentences, 1-4s between paragraphs, 2-8s for "thinking"
- Rewrites should be natural — type a plausible but slightly worse version first, then fix it
- Speed multipliers: 0.5 = very slow/careful, 1.0 = normal, 1.5 = fast burst
- Don't overdo mistakes — real humans make typos on roughly 3-5% of words
- Make the typing feel ALIVE, not mechanical
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
- Rewrite probability: {self.settings.rewrite_probability}
- Fatigue enabled: {self.settings.fatigue_enabled}
- Burst typing enabled: {self.settings.burst_typing_enabled}

Text to type:
---
{full_text}
---

Generate the typing plan as JSON. Make it feel like a real person typing this for the first time. \
Include {max(1, int(word_count * self.settings.error_rate))} typos and \
{max(0, int(word_count * self.settings.rewrite_probability))} rewrites spread naturally throughout."""

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
                actions.append(Rewrite(
                    delete_count=len(first_attempt),
                    new_text=final_version,
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
    """Uses Claude to generate plausible 'first draft' versions of sentences
    that a human might type before deleting and rewriting better."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client: Optional[anthropic.Anthropic] = None
        self._enabled = bool(self._api_key)

        if self._api_key:
            try:
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except Exception:
                self._enabled = False

    def generate_first_draft(self, final_text: str, context: str = "") -> Optional[str]:
        """Generate a plausible worse first attempt of a sentence.

        Args:
            final_text: The final/correct version of the text.
            context: Surrounding text for context.

        Returns:
            A plausible first-draft version, or None if AI is unavailable.
        """
        if not self._enabled or not self._client:
            return None

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=30.0,
                max_tokens=200,
                system=(
                    "You generate plausible first-draft versions of sentences. "
                    "Given a final polished sentence, return a slightly rougher version "
                    "that someone might type first before editing. Make it slightly "
                    "wordier, less precise, or with a different word choice. "
                    "Return ONLY the draft text, nothing else."
                ),
                messages=[{
                    "role": "user",
                    "content": f"Final version: {final_text}\nContext: {context}\n\nFirst draft:",
                }],
            )
            draft = response.content[0].text.strip()
            # Sanity check — draft should be similar length, not wildly different
            if 0.5 < len(draft) / max(len(final_text), 1) < 2.0:
                return draft
            return None
        except Exception:
            logger.exception("AI rewriter failed")
            return None
