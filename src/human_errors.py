"""AI-powered human-realistic typos, misspellings, and grammar errors.

Uses Claude to generate contextually appropriate errors that mimic
a real teenager's typing — grammar mistakes, punctuation errors,
textese leaks, and misspellings. No hardcoded word lists or patterns.
"""

from __future__ import annotations

import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Optional

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

HUMAN_ERRORS_SYSTEM_PROMPT = """\
You are simulating a 16-year-old student's typing errors. Given text that a teen \
is about to type for a school assignment, you produce TWO things:

1. **modified_text**: The text with realistic permanent errors baked in — errors \
the teen would NOT notice or fix. These include:
   - Grammar errors: your/you're confusion, their/there/they're, its/it's, \
"could of" instead of "could have", "alot", than/then confusion, etc.
   - Punctuation errors: missing apostrophes in contractions (dont, cant, wont, im), \
missing commas before conjunctions, run-on sentences, comma splices, lowercase "i", \
missing commas after introductory phrases.
   - Textese leaks: occasional "bc" for because, "tbh", "rn", "idk", "gonna", \
"wanna", "prolly", "thru" — but very sparingly (only ~1-2 per page max).
   - Keep these errors SUBTLE and SPARSE — a real teen doesn't make errors on \
every sentence. Maybe 2-5 permanent errors per paragraph depending on length.

2. **misspellings**: A list of words the teen will type wrong but then NOTICE and \
FIX (backspace and retype). These are temporary keystroke errors like:
   - Transpositions: "teh" for "the", "taht" for "that"
   - Letter swaps: "becuase" for "because"
   - Doubled letters: "goood" for "good"
   - Skipped letters: "thnk" for "think"
   - Pick ~3-8% of words to misspell, focusing on longer and less common words.

Return a JSON object with this EXACT structure:
{
  "modified_text": "the full text with permanent errors applied",
  "misspellings": [
    {"wrong": "teh", "correct": "the", "position": 0},
    {"wrong": "becuase", "correct": "because", "position": 45}
  ]
}

CRITICAL RULES:
- modified_text must be the SAME LENGTH structure as the input (same sentences, \
same paragraph breaks). Do NOT add or remove sentences.
- Misspelling positions are character offsets in the modified_text (after permanent \
errors are applied).
- Each misspelling's "correct" field must match the actual word at that position \
in modified_text.
- Do NOT misspell proper nouns, technical terms, or very short words (a, I, is, etc.)
- Return ONLY the JSON, nothing else.\
"""

THOUGHT_BOUNDARIES_SYSTEM_PROMPT = """\
You analyze text to find "thought boundaries" — places where the writer shifts \
to a new idea, changes topic, introduces a contrast, adds a new point, gives an \
example, or transitions between concepts.

Given text, return a JSON array of character positions where thought boundaries occur. \
These are positions where a real person typing would pause longer to gather their \
thoughts before continuing.

Return ONLY a JSON array of integers, nothing else. Example: [0, 145, 289, 512]\
"""


class HumanErrors:
    """AI-powered human error generator. Falls back to no-op if API unavailable."""

    MAX_REQUESTS_PER_PLAN = 4
    MAX_INPUT_CHARS = 8000
    MAX_OUTPUT_TOKENS = 4096

    def __init__(
        self,
        misspelling_rate: float = 0.03,
        grammar_error_rate: float = 0.15,
        punctuation_error_rate: float = 0.2,
        seed: int | None = None,
        api_key: str | None = None,
        enabled: bool = True,
    ):
        self._requests = 0
        self.misspelling_rate = misspelling_rate
        self.grammar_error_rate = grammar_error_rate
        self.punctuation_error_rate = punctuation_error_rate

        self._api_key = (api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")) if enabled else None
        self._client: Optional[anthropic.Anthropic] = None
        self._enabled = bool(self._api_key)

        if self._api_key:
            try:
                self._client = anthropic.Anthropic(api_key=self._api_key, max_retries=0)
            except Exception:
                logger.exception("Failed to initialize Anthropic client for HumanErrors")
                self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    def reset_budget(self) -> None:
        """Each paste receives a bounded budget, including failed requests."""
        self._requests = 0

    def _reserve_request(self) -> bool:
        if self._requests >= self.MAX_REQUESTS_PER_PLAN:
            return False
        self._requests += 1
        return True

    def process_text(self, text: str) -> tuple[str, list[tuple[str, str, int]]]:
        """Apply all human errors to text using AI.

        Returns:
            (modified_text, misspellings_to_fix)
            - modified_text has grammar/punctuation/textese errors baked in (not corrected)
            - misspellings_to_fix is a list of (wrong, correct, pos) that the
              typing engine should type wrong then fix
        """
        if (not self.is_enabled or not text.strip()
                or len(text) > self.MAX_INPUT_CHARS or not self._reserve_request()):
            return text, []

        try:
            return self._ai_process_text(text)
        except Exception:
            logger.exception("AI human errors failed, returning text unchanged")
            return text, []

    def _ai_process_text(self, text: str) -> tuple[str, list[tuple[str, str, int]]]:
        """Call Claude to generate realistic human errors."""
        word_count = len(text.split())
        misspelling_count = max(1, int(word_count * self.misspelling_rate))
        grammar_note = ""
        if self.grammar_error_rate < 0.05:
            grammar_note = "Very few grammar errors (this student is careful). "
        elif self.grammar_error_rate > 0.25:
            grammar_note = "More grammar errors than average (this student rushes). "

        punct_note = ""
        if self.punctuation_error_rate < 0.05:
            punct_note = "Very few punctuation errors. "
        elif self.punctuation_error_rate > 0.30:
            punct_note = "Frequent punctuation errors (lazy with commas/apostrophes). "

        user_prompt = (
            f"{grammar_note}{punct_note}"
            f"Target about {misspelling_count} misspellings to fix.\n\n"
            f"Text ({word_count} words):\n---\n{text}\n---"
        )

        response = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            timeout=45.0,
            max_tokens=min(self.MAX_OUTPUT_TOKENS, max(512, len(text))),
            system=HUMAN_ERRORS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if getattr(response, "stop_reason", None) == "max_tokens" or not response.content:
            return text, []
        response_text = response.content[0].text.strip()

        # Parse JSON
        data = self._parse_json(response_text)
        if not isinstance(data, dict):
            return text, []

        modified_text = data.get("modified_text", text)
        if not self._valid_modified_text(text, modified_text):
            return text, []
        raw_misspellings = data.get("misspellings", [])
        if not isinstance(raw_misspellings, list):
            raw_misspellings = []

        # Convert misspellings to tuple format, validating positions
        misspellings: list[tuple[str, str, int]] = []
        for m in raw_misspellings[:100]:
            if not isinstance(m, dict):
                continue
            wrong = m.get("wrong", "")
            correct = m.get("correct", "")
            pos = m.get("position", -1)
            if (isinstance(wrong, str) and isinstance(correct, str)
                    and wrong and correct and len(wrong) <= 100 and len(correct) <= 100
                    and wrong.isascii() and wrong.isprintable()
                    and not any(c.isspace() for c in wrong + correct)
                    and isinstance(pos, int) and not isinstance(pos, bool) and pos >= 0):
                # Validate the position — the correct word should be at that position
                if pos < len(modified_text):
                    actual_word = modified_text[pos:pos + len(correct)]
                    if actual_word.lower() == correct.lower():
                        misspellings.append((wrong, actual_word, pos))
                    else:
                        # Try to find the word nearby (AI positions can be off)
                        found_pos = self._find_word_near(modified_text, correct, pos)
                        if found_pos >= 0:
                            misspellings.append((wrong, modified_text[found_pos:found_pos + len(correct)], found_pos))

        return modified_text, misspellings

    @staticmethod
    def _valid_modified_text(original: str, modified: object) -> bool:
        """Permit sparse grammar edits, never wholesale AI replacement or lost lines."""
        if not isinstance(modified, str):
            return False
        before, after = original.split("\n"), modified.split("\n")
        if len(before) != len(after):
            return False
        for source, result in zip(before, after):
            if not source.strip():
                if result != source:
                    return False
                continue
            if not result.strip() or len(result) > len(source) * 1.25:
                return False
            # Trim shared edges before matching: one typo in repetitive text
            # must not make an 8000-character line a quadratic comparison.
            prefix = 0
            limit = min(len(source), len(result))
            while prefix < limit and source[prefix] == result[prefix]:
                prefix += 1
            suffix = 0
            while (suffix < limit - prefix
                   and source[len(source) - suffix - 1] == result[len(result) - suffix - 1]):
                suffix += 1
            source_end = len(source) - suffix
            result_end = len(result) - suffix
            changed_source, changed_result = source[prefix:source_end], result[prefix:result_end]
            matcher = SequenceMatcher(None, changed_source, changed_result, autojunk=True)
            matched = prefix + suffix + sum(block.size for block in matcher.get_matching_blocks())
            if 2 * matched / (len(source) + len(result)) < .8:
                return False
            for tag, start, end, result_start, result_end in matcher.get_opcodes():
                if tag == "equal":
                    continue
                removed = changed_source[start:end]
                inserted = changed_result[result_start:result_end]
                # AI grammar edits must not add or remove keyboard controls.
                # Keep source tabs and Unicode formatting intact when they
                # are unchanged, but never turn prose into Tab/Return/etc.
                if any(not char.isprintable() for char in removed + inserted):
                    return False
                # Grammar and punctuation mistakes are small local edits. A
                # similar surrounding paragraph cannot justify losing a sentence
                # or substituting a large section of clipboard text.
                if max(len(removed), len(inserted)) > 24:
                    return False
                if re.search(r"\w[^.!?]*[.!?](?:\s|$)", removed):
                    return False
            # Preserve paragraph indentation and separators exactly.
            for pattern in (r"^\s*", r"\s*$"):
                if re.search(pattern, source).group() != re.search(pattern, result).group():
                    return False
        return True

    def find_thought_boundaries(self, text: str) -> list[int]:
        """Use AI to identify thought boundary positions in text.

        Returns list of character positions where the writer shifts ideas.
        """
        if not self.is_enabled or len(text) < 50 or not self._reserve_request():
            return []
        text = text[:self.MAX_INPUT_CHARS]

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                timeout=30.0,
                max_tokens=1024,
                system=THOUGHT_BOUNDARIES_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
            )

            response_text = response.content[0].text.strip()
            positions = json.loads(response_text)
            if isinstance(positions, list):
                return [p for p in positions if isinstance(p, int) and 0 <= p < len(text)]
            return []
        except Exception:
            logger.exception("AI thought boundary detection failed")
            return []

    @staticmethod
    def _find_word_near(text: str, word: str, approximate_pos: int, window: int = 30) -> int:
        """Find a word near an approximate position."""
        start = max(0, approximate_pos - window)
        end = min(len(text), approximate_pos + window + len(word))
        # Match against the full source so a search-window edge cannot invent
        # a word boundary. Relocate only to the uniquely nearest occurrence.
        pattern = r"\b" + re.escape(word) + r"\b"
        positions = [match.start() for match in re.finditer(pattern, text, re.IGNORECASE)
                     if start <= match.start() and match.end() <= end]
        if not positions:
            return -1
        distance = min(abs(position - approximate_pos) for position in positions)
        nearest = [position for position in positions if abs(position - approximate_pos) == distance]
        return nearest[0] if len(nearest) == 1 else -1

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Extract and parse JSON from response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try markdown code fence
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object
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
                            return json.loads(text[brace_start:i + 1])
                        except json.JSONDecodeError:
                            break

        return None
