"""Tests for sentence/paragraph boundary flags in text chunking.

Audits how _break_into_chunks() sets is_sentence_end and is_paragraph_end,
and verifies that proofreading can trigger at every sentence boundary.
"""

import re
import sys
import os

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.typing_planner import TypingPlanner, _Chunk, SENTENCE_RE, PHRASE_RE
from src.human_errors import HumanErrors


def get_chunks(text: str) -> list[_Chunk]:
    """Helper: break text into chunks using a real TypingPlanner."""
    planner = TypingPlanner()
    return planner._break_into_chunks(text)


def dump_chunks(chunks: list[_Chunk]) -> None:
    """Pretty-print chunks for debugging."""
    for i, c in enumerate(chunks):
        flags = []
        if c.is_sentence_end:
            flags.append("SENTENCE_END")
        if c.is_paragraph_end:
            flags.append("PARAGRAPH_END")
        if c.is_thought_boundary:
            flags.append("THOUGHT_BOUNDARY")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  chunk[{i}]: {c.text!r}{flag_str}")


# =====================================================================
# Test 1: Three-sentence single paragraph — the core case
# =====================================================================

def test_three_sentences_single_paragraph():
    """The Industrial Revolution example: 3 sentences, 1 paragraph.

    Expected behaviour for proofreading to work:
    - Sentences 1 and 2 should have is_sentence_end=True on their last chunk
    - Sentence 3 (last) should have is_paragraph_end=True on its last chunk
    - The proofread check is `chunk.is_sentence_end or chunk.is_paragraph_end`
      so ALL sentence boundaries should be eligible for proofreading.
    """
    text = "The Industrial Revolution began in Britain. It changed how goods were made. Factories replaced small workshops."
    chunks = get_chunks(text)

    print("\n=== Test 1: Three sentences, single paragraph ===")
    dump_chunks(chunks)

    # First, verify the SENTENCE_RE split
    sentences = SENTENCE_RE.split(text)
    print(f"\n  SENTENCE_RE splits into {len(sentences)} sentences:")
    for i, s in enumerate(sentences):
        print(f"    [{i}]: {s!r}")

    # Collect flags
    sentence_end_chunks = [c for c in chunks if c.is_sentence_end]
    paragraph_end_chunks = [c for c in chunks if c.is_paragraph_end]
    proofreadable = [c for c in chunks if c.is_sentence_end or c.is_paragraph_end]

    print(f"\n  Chunks with is_sentence_end=True: {len(sentence_end_chunks)}")
    print(f"  Chunks with is_paragraph_end=True: {len(paragraph_end_chunks)}")
    print(f"  Chunks eligible for proofreading: {len(proofreadable)}")

    # We have 3 sentences. The first 2 should trigger is_sentence_end,
    # the last should trigger is_paragraph_end.
    # BUG CHECK: line 347 says:
    #   is_sentence_end=is_last_phrase and not is_last_sentence
    # This means the LAST sentence never gets is_sentence_end=True.
    # But it DOES get is_paragraph_end=True (line 348).
    # The proofread check on line 212 is:
    #   if (chunk.is_sentence_end or chunk.is_paragraph_end) and pending_typos:
    # So the last sentence IS covered via is_paragraph_end. Good.

    assert len(sentence_end_chunks) == 2, (
        f"Expected 2 chunks with is_sentence_end=True (sentences 1 and 2), got {len(sentence_end_chunks)}"
    )
    assert len(paragraph_end_chunks) == 1, (
        f"Expected 1 chunk with is_paragraph_end=True (sentence 3), got {len(paragraph_end_chunks)}"
    )
    assert len(proofreadable) == 3, (
        f"Expected 3 proofreadable boundaries (all 3 sentences), got {len(proofreadable)}"
    )

    # Verify that sentence_end and paragraph_end are mutually exclusive per the logic
    for c in chunks:
        if c.is_paragraph_end:
            assert not c.is_sentence_end, (
                f"Chunk {c.text!r} has BOTH is_sentence_end and is_paragraph_end; "
                "the logic makes them mutually exclusive (not is_last_sentence)"
            )


# =====================================================================
# Test 2: Single sentence — only paragraph_end, no sentence_end
# =====================================================================

def test_single_sentence():
    """A single sentence: the only chunk gets is_paragraph_end=True but
    NOT is_sentence_end=True (because it's the last sentence).
    Proofreading still triggers because the check uses `or`.
    """
    text = "The cat sat on the mat."
    chunks = get_chunks(text)

    print("\n=== Test 2: Single sentence ===")
    dump_chunks(chunks)

    sentence_end_chunks = [c for c in chunks if c.is_sentence_end]
    paragraph_end_chunks = [c for c in chunks if c.is_paragraph_end]
    proofreadable = [c for c in chunks if c.is_sentence_end or c.is_paragraph_end]

    assert len(sentence_end_chunks) == 0, (
        f"Single sentence should have 0 is_sentence_end chunks, got {len(sentence_end_chunks)}"
    )
    assert len(paragraph_end_chunks) == 1, (
        f"Single sentence should have 1 is_paragraph_end chunk, got {len(paragraph_end_chunks)}"
    )
    assert len(proofreadable) == 1, "Single sentence should still be proofreadable via is_paragraph_end"


# =====================================================================
# Test 3: Two paragraphs
# =====================================================================

def test_two_paragraphs():
    """Two paragraphs separated by double newline.
    Each paragraph's last sentence gets is_paragraph_end.
    Non-last sentences get is_sentence_end.
    The newline chunk also gets is_paragraph_end.
    """
    text = "First sentence. Second sentence.\n\nThird sentence. Fourth sentence."
    chunks = get_chunks(text)

    print("\n=== Test 3: Two paragraphs ===")
    dump_chunks(chunks)

    sentence_end_chunks = [c for c in chunks if c.is_sentence_end]
    paragraph_end_chunks = [c for c in chunks if c.is_paragraph_end]

    # Paragraph 1: "First sentence. " -> is_sentence_end, "Second sentence." -> is_paragraph_end
    # Newline chunk: is_paragraph_end
    # Paragraph 2: "Third sentence. " -> is_sentence_end, "Fourth sentence." -> is_paragraph_end
    print(f"\n  is_sentence_end count: {len(sentence_end_chunks)}")
    print(f"  is_paragraph_end count: {len(paragraph_end_chunks)}")

    assert len(sentence_end_chunks) == 2, (
        f"Expected 2 is_sentence_end (sentences 1 and 3), got {len(sentence_end_chunks)}"
    )
    # 2 paragraph-final sentences + 1 newline chunk = 3
    assert len(paragraph_end_chunks) == 3, (
        f"Expected 3 is_paragraph_end (2 final sentences + 1 newline), got {len(paragraph_end_chunks)}"
    )


# =====================================================================
# Test 4: Sentence with phrases (commas) — only last phrase gets flag
# =====================================================================

def test_sentence_with_phrases():
    """A sentence with commas splits into phrases.
    Only the LAST phrase of a sentence gets is_sentence_end.
    """
    text = "When the sun rose, the birds sang, and the day began. It was beautiful."
    chunks = get_chunks(text)

    print("\n=== Test 4: Sentence with phrases ===")
    dump_chunks(chunks)

    # Sentence 1 has commas -> splits into phrases. Only the last phrase
    # of sentence 1 gets is_sentence_end.
    sentence_end_chunks = [c for c in chunks if c.is_sentence_end]
    paragraph_end_chunks = [c for c in chunks if c.is_paragraph_end]

    assert len(sentence_end_chunks) == 1, (
        f"Expected 1 is_sentence_end (last phrase of sentence 1), got {len(sentence_end_chunks)}"
    )
    assert len(paragraph_end_chunks) == 1, (
        f"Expected 1 is_paragraph_end (sentence 2 final), got {len(paragraph_end_chunks)}"
    )


# =====================================================================
# Test 5: SENTENCE_RE regex behaviour
# =====================================================================

def test_sentence_regex_splitting():
    """Verify SENTENCE_RE splits correctly at '. ' boundaries."""
    print("\n=== Test 5: SENTENCE_RE regex ===")

    # Normal case: splits after ". " before a non-space char
    text = "Hello world. Goodbye world. The end."
    parts = SENTENCE_RE.split(text)
    print(f"  {text!r} -> {parts}")
    assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}: {parts}"

    # Trailing period with no following text — no split
    text2 = "Just one sentence."
    parts2 = SENTENCE_RE.split(text2)
    assert len(parts2) == 1, f"Expected 1 part, got {len(parts2)}"

    # Question mark and exclamation
    text3 = "Really? Yes! Absolutely."
    parts3 = SENTENCE_RE.split(text3)
    print(f"  {text3!r} -> {parts3}")
    assert len(parts3) == 3, f"Expected 3 parts, got {len(parts3)}: {parts3}"

    # Edge: no space after period (abbreviation-like) — should NOT split
    text4 = "Dr.Smith went home."
    parts4 = SENTENCE_RE.split(text4)
    print(f"  {text4!r} -> {parts4}")
    assert len(parts4) == 1, f"Dr.Smith should not split: got {len(parts4)}"

    # Edge: multiple spaces after period
    text5 = "First sentence.  Second sentence."
    parts5 = SENTENCE_RE.split(text5)
    print(f"  {text5!r} -> {parts5}")
    # The regex requires (?<=[.!?]\s) — a single \s after [.!?].
    # With double space: "First sentence. " ends with ". ", and the lookbehind
    # matches " " (second space is the \s in lookbehind), then lookahead is "S".
    # Actually the lookbehind (?<=[.!?]\s) matches ". " at the position after
    # the first space. Then (?=\S) fails because next char is another space.
    # At position after second space, lookbehind is " S" which doesn't match [.!?]\s.
    # Hmm, let's just check what actually happens.
    print(f"  Double-space split count: {len(parts5)}")


# =====================================================================
# Test 6: human_errors.process_text() breaking sentence boundaries
# =====================================================================

def test_human_errors_break_sentence_splitting():
    """When human_errors removes periods (run-on sentence error), the
    SENTENCE_RE regex won't find the boundary, so that sentence boundary
    gets NO is_sentence_end flag.

    This is a known consequence: if process_text() turns
      "First sentence. Second sentence."
    into
      "First sentence second sentence."
    then there's only 1 "sentence" from SENTENCE_RE's perspective.
    """
    print("\n=== Test 6: human_errors breaking sentence boundaries ===")

    # Simulate the run-on sentence error manually
    # (The actual error is probabilistic, so we apply it directly)
    original = "The dog ran fast. The cat slept all day."
    # Run-on: period+space+Capital -> space+lowercase
    run_on = "The dog ran fast the cat slept all day."

    original_chunks = get_chunks(original)
    run_on_chunks = get_chunks(run_on)

    print("  Original text chunks:")
    dump_chunks(original_chunks)
    print("  Run-on text chunks:")
    dump_chunks(run_on_chunks)

    orig_proofreadable = [c for c in original_chunks if c.is_sentence_end or c.is_paragraph_end]
    runon_proofreadable = [c for c in run_on_chunks if c.is_sentence_end or c.is_paragraph_end]

    print(f"\n  Original proofreadable boundaries: {len(orig_proofreadable)}")
    print(f"  Run-on proofreadable boundaries: {len(runon_proofreadable)}")

    # Original has 2 sentences -> 2 proofreadable (1 sentence_end + 1 paragraph_end)
    assert len(orig_proofreadable) == 2

    # Run-on merges into 1 sentence -> only 1 proofreadable (paragraph_end)
    assert len(runon_proofreadable) == 1, (
        f"Run-on sentence should have only 1 proofreadable boundary (paragraph_end), "
        f"got {len(runon_proofreadable)}"
    )

    print("  WARNING: Run-on sentence errors reduce proofreading opportunities!")


# =====================================================================
# Test 7: Edge case — text with no sentence-ending punctuation
# =====================================================================

def test_no_punctuation():
    """Text with no periods/question marks/exclamation marks.
    SENTENCE_RE won't split at all. The entire text is one 'sentence'.
    The last chunk still gets is_paragraph_end=True.
    """
    text = "This is some text without any ending punctuation"
    chunks = get_chunks(text)

    print("\n=== Test 7: No punctuation ===")
    dump_chunks(chunks)

    sentence_end_chunks = [c for c in chunks if c.is_sentence_end]
    paragraph_end_chunks = [c for c in chunks if c.is_paragraph_end]

    assert len(sentence_end_chunks) == 0
    assert len(paragraph_end_chunks) == 1
    print("  Still proofreadable via is_paragraph_end at the end.")


# =====================================================================
# Test 8: Edge case — empty text and whitespace-only
# =====================================================================

def test_empty_and_whitespace():
    """Empty or whitespace-only text should produce no chunks."""
    print("\n=== Test 8: Empty and whitespace ===")

    assert get_chunks("") == []
    assert get_chunks("   ") == []
    assert get_chunks("\n\n") == []
    print("  All empty cases produce no chunks. Good.")


# =====================================================================
# Test 9: Verify the mutual exclusivity bug is intentional
# =====================================================================

def test_sentence_end_paragraph_end_mutual_exclusivity():
    """The logic on line 347:
        is_sentence_end=is_last_phrase and not is_last_sentence

    This means for the LAST sentence of a paragraph, is_sentence_end
    is always False. Only is_paragraph_end is True.

    This is by design: the last sentence boundary is a "paragraph end",
    not a "sentence end". The proofread check (line 212) uses OR so both
    flags trigger proofreading. But the pause logic differs:
    - is_sentence_end -> sentence pause (line 477)
    - is_paragraph_end -> paragraph pause (line 479-480)

    The last sentence gets a paragraph pause, not a sentence pause. This
    seems intentional (you'd want a longer pause at paragraph end).
    """
    print("\n=== Test 9: Mutual exclusivity of sentence_end / paragraph_end ===")

    text = "A. B. C."
    chunks = get_chunks(text)
    dump_chunks(chunks)

    # chunk for "A. " -> is_sentence_end=True (not last sentence)
    # chunk for "B. " -> is_sentence_end=True (not last sentence)
    # chunk for "C." -> is_paragraph_end=True, is_sentence_end=False (last sentence)
    for c in chunks:
        assert not (c.is_sentence_end and c.is_paragraph_end), (
            f"Chunk {c.text!r} has both flags set — should be mutually exclusive"
        )

    # The last chunk must have paragraph_end
    assert chunks[-1].is_paragraph_end
    assert not chunks[-1].is_sentence_end


# =====================================================================
# Test 10: Verify the proofread condition covers all cases
# =====================================================================

def test_proofread_condition_coverage():
    """Exhaustive check: for any number of sentences in a single paragraph,
    every sentence boundary must be covered by (is_sentence_end or is_paragraph_end).
    """
    print("\n=== Test 10: Proofread condition coverage ===")

    test_cases = [
        ("One.", 1),
        ("One. Two.", 2),
        ("One. Two. Three.", 3),
        ("One. Two. Three. Four. Five.", 5),
    ]

    for text, expected_sentences in test_cases:
        chunks = get_chunks(text)
        proofreadable = [c for c in chunks if c.is_sentence_end or c.is_paragraph_end]
        print(f"  {text!r}: {expected_sentences} sentences, {len(proofreadable)} proofreadable boundaries")
        assert len(proofreadable) == expected_sentences, (
            f"For {expected_sentences} sentences, expected {expected_sentences} "
            f"proofreadable boundaries, got {len(proofreadable)}"
        )

    print("  All sentence counts produce correct proofreadable boundary counts.")


# =====================================================================
# Run all tests
# =====================================================================

if __name__ == "__main__":
    test_three_sentences_single_paragraph()
    test_single_sentence()
    test_two_paragraphs()
    test_sentence_with_phrases()
    test_sentence_regex_splitting()
    test_human_errors_break_sentence_splitting()
    test_no_punctuation()
    test_empty_and_whitespace()
    test_sentence_end_paragraph_end_mutual_exclusivity()
    test_proofread_condition_coverage()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print()
    print("SUMMARY OF FINDINGS:")
    print("1. is_sentence_end and is_paragraph_end are MUTUALLY EXCLUSIVE.")
    print("   The last sentence of a paragraph gets is_paragraph_end=True,")
    print("   NOT is_sentence_end=True.")
    print("2. The proofread check uses (is_sentence_end OR is_paragraph_end),")
    print("   so ALL sentence boundaries trigger proofreading. No bug here.")
    print("3. human_errors.process_text() CAN remove periods (run-on sentence")
    print("   error), which merges sentences and reduces proofreading")
    print("   opportunities. This is a known trade-off.")
    print("4. Text with no punctuation still gets 1 proofreadable boundary")
    print("   (is_paragraph_end on the final chunk).")
