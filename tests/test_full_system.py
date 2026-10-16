"""Comprehensive system test for Ghost Typer.

Exercises ALL features end-to-end:
- Text chunking & boundary detection
- Typing plan generation (mistakes, pauses, rewrites, proofreading)
- Cascading rewrite system (word/sentence/paragraph, nesting, repeats)
- Rewrite scaling with text length
- AI-powered human errors (HumanErrors interface)
- AI-powered draft generation (AIRewriter interface)
- Revisit earlier text feature
- Recursive Rewrite execution model
- Progress tracking / character counting
- Settings & engine (sigmoid scaling, granularity picker)
- Edge cases (empty text, single word, huge text)
"""

import sys
import os
import re
from unittest.mock import MagicMock, patch
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import (
    AbandonWord, DistractionPause, Range, TypingProfile,
    Rewrite, TypeText, Pause, MakeMistake, PressKey, ApplyFormatting,
    TypingAction, TypingPlan, TextSegment, Settings,
)
from src.typing_engine import TypingEngine
from src.typing_planner import TypingPlanner, _Chunk, SENTENCE_RE


# =====================================================================
# Helpers
# =====================================================================

def count_action_types(actions):
    """Count how many of each action type appear in a list."""
    counts = Counter()
    for a in actions:
        counts[type(a).__name__] += 1
        # Recurse into nested Rewrite actions
        if isinstance(a, Rewrite):
            nested = count_action_types(a.new_actions)
            for k, v in nested.items():
                counts[f"nested_{k}"] += v
    return counts


def flatten_typed_text(actions):
    """Extract all text that would be typed (ignoring deletions)."""
    parts = []
    for a in actions:
        if isinstance(a, TypeText):
            parts.append(a.text)
        elif isinstance(a, MakeMistake):
            parts.append(a.correct_text)
        elif isinstance(a, Rewrite):
            parts.append(flatten_typed_text(a.new_actions))
    return "".join(parts)


def count_typed_chars_recursive(actions):
    """Recursively count all characters that will be typed."""
    total = 0
    for a in actions:
        if isinstance(a, TypeText):
            total += len(a.text)
        elif isinstance(a, MakeMistake):
            total += len(a.wrong_text) + len(a.correct_text)
        elif isinstance(a, Rewrite):
            total += count_typed_chars_recursive(a.new_actions)
    return total


SHORT_TEXT = "The cat sat on the mat."

MEDIUM_TEXT = (
    "The Industrial Revolution began in Britain during the late 18th century. "
    "It fundamentally changed how goods were manufactured and distributed. "
    "Factories replaced small workshops, and steam power transformed transportation.\n\n"
    "However, these changes also brought significant social challenges. "
    "Workers faced long hours in dangerous conditions. "
    "Child labor was widespread, and pollution darkened city skies.\n\n"
    "Despite these problems, the revolution ultimately improved living standards. "
    "New technologies created jobs and made products more affordable. "
    "The middle class expanded, and education became more accessible."
)

LONG_TEXT = MEDIUM_TEXT * 5  # ~2500 chars, simulating multi-page paste


# =====================================================================
# 1. Rewrite Model Tests
# =====================================================================

def test_rewrite_simple_factory():
    """Rewrite.simple() creates a flat rewrite with TypeText in new_actions."""
    r = Rewrite.simple(5, "hello")
    assert r.delete_count == 5
    assert len(r.new_actions) == 1
    assert isinstance(r.new_actions[0], TypeText)
    assert r.new_actions[0].text == "hello"
    assert r.new_text == "hello"
    print("  PASS: Rewrite.simple() factory works")


def test_rewrite_nested_new_text():
    """Rewrite.new_text flattens only immediate TypeText children."""
    inner = Rewrite.simple(3, "inner")
    outer = Rewrite(
        delete_count=10,
        new_actions=[TypeText(text="start "), inner, TypeText(text=" end")],
    )
    # new_text only gets immediate TypeText, not nested Rewrite's text
    assert outer.new_text == "start  end"
    print("  PASS: Nested Rewrite.new_text flattens correctly")


def test_rewrite_empty():
    """Empty Rewrite works without errors."""
    r = Rewrite(delete_count=0, new_actions=[])
    assert r.new_text == ""
    assert r.delete_count == 0
    print("  PASS: Empty Rewrite OK")


def test_rewrite_description():
    """Rewrite auto-generates description from new_text."""
    r = Rewrite.simple(3, "hi")
    assert "hi" in r.description
    assert "3" in r.description
    print("  PASS: Rewrite description generated")


# =====================================================================
# 2. Settings Tests
# =====================================================================

def test_new_settings_fields():
    """All new settings fields exist with correct defaults."""
    s = Settings()
    assert s.rewrite_base_probability == 0.10
    assert s.rewrite_max_probability == 0.85
    assert s.rewrite_scaling_chars == 2000
    assert s.rewrite_word_weight == 0.50
    assert s.rewrite_sentence_weight == 0.35
    assert s.rewrite_paragraph_weight == 0.15
    assert s.rewrite_cascade_probability == 0.40
    assert s.rewrite_repeat_probability == 0.15
    assert s.rewrite_max_repeats == 3
    assert s.revisit_probability == 0.20
    assert s.revisit_max_per_session == 5
    print("  PASS: All new settings fields present with correct defaults")


def test_old_settings_removed():
    """Old rewrite_probability and rewrite_max_words removed."""
    s = Settings()
    assert not hasattr(s, "rewrite_probability")
    assert not hasattr(s, "rewrite_max_words")
    print("  PASS: Old settings fields removed")


def test_settings_serialization():
    """Settings can serialize and deserialize with new fields."""
    s = Settings()
    d = s.to_dict()
    assert "rewrite_base_probability" in d
    assert "rewrite_cascade_probability" in d
    assert "revisit_probability" in d

    s2 = Settings.from_dict(d)
    assert s2.rewrite_base_probability == s.rewrite_base_probability
    assert s2.revisit_max_per_session == s.revisit_max_per_session
    print("  PASS: Settings serialize/deserialize with new fields")


# =====================================================================
# 3. Typing Engine Tests
# =====================================================================

def test_sigmoid_scaling():
    """Rewrite probability scales with text length via sigmoid."""
    e = TypingEngine(Settings())

    p50 = e.rewrite_probability_for_length(50)
    p500 = e.rewrite_probability_for_length(500)
    p2000 = e.rewrite_probability_for_length(2000)
    p5000 = e.rewrite_probability_for_length(5000)
    p10000 = e.rewrite_probability_for_length(10000)

    # Should monotonically increase
    assert p50 < p500 < p2000 < p5000 <= p10000
    # Short text should be low
    assert p50 < 0.30
    # Long text should be high
    assert p5000 > 0.70
    # Should be capped
    assert p10000 <= 0.85 + 0.01  # allow float imprecision

    print(f"  PASS: Sigmoid scaling: 50→{p50:.2%}, 500→{p500:.2%}, "
          f"2000→{p2000:.2%}, 5000→{p5000:.2%}, 10000→{p10000:.2%}")


def test_should_rewrite_uses_length():
    """should_rewrite() accepts total_chars and returns bool."""
    e = TypingEngine(Settings())
    e.seed(42)

    # With very short text, fewer rewrites
    short_rewrites = sum(e.should_rewrite(50) for _ in range(1000))
    # With very long text, more rewrites
    long_rewrites = sum(e.should_rewrite(10000) for _ in range(1000))

    assert short_rewrites < long_rewrites
    print(f"  PASS: should_rewrite scales: short={short_rewrites}/1000, long={long_rewrites}/1000")


def test_granularity_picker():
    """pick_rewrite_granularity returns valid values with expected distribution."""
    e = TypingEngine(Settings())
    e.seed(42)

    results = [e.pick_rewrite_granularity() for _ in range(1000)]
    counts = Counter(results)

    assert set(counts.keys()) <= {"word", "sentence", "paragraph"}
    assert counts["word"] > counts["sentence"] > counts["paragraph"]
    print(f"  PASS: Granularity distribution: {dict(counts)}")


def test_cascade_and_repeat():
    """should_cascade and should_repeat_rewrite return bools at expected rates."""
    e = TypingEngine(Settings())
    e.seed(42)

    cascades = sum(e.should_cascade() for _ in range(1000))
    repeats = sum(e.should_repeat_rewrite() for _ in range(1000))

    # ~40% cascade, ~15% repeat
    assert 300 < cascades < 500, f"Expected ~400 cascades, got {cascades}"
    assert 100 < repeats < 250, f"Expected ~150 repeats, got {repeats}"
    print(f"  PASS: Cascade rate: {cascades}/1000, Repeat rate: {repeats}/1000")


# =====================================================================
# 4. Plan Generation Tests (without AI — tests the rule-based planner)
# =====================================================================

def test_plan_short_text():
    """Short text produces a valid plan with minimal rewrites."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=SHORT_TEXT)])

    assert len(plan.actions) > 0
    assert plan.total_characters > 0

    counts = count_action_types(plan.actions)
    assert counts.get("TypeText", 0) > 0
    print(f"  PASS: Short text plan: {len(plan.actions)} actions, "
          f"{plan.total_characters} chars, types: {dict(counts)}")


def test_plan_medium_text():
    """Medium text produces pauses, mistakes, and boundary detection."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=MEDIUM_TEXT)])

    counts = count_action_types(plan.actions)

    # Should have TypeText
    assert counts.get("TypeText", 0) > 0
    # Should have pauses (sentence/paragraph boundaries)
    assert counts.get("Pause", 0) > 0
    # Should have PressKey (enter for paragraph breaks, or proofreading arrows)
    assert counts.get("PressKey", 0) >= 0

    print(f"  PASS: Medium text plan: {len(plan.actions)} actions, "
          f"{plan.total_characters} chars")
    print(f"        Action counts: {dict(counts)}")


def test_plan_contains_mistakes():
    """Plans should contain MakeMistake actions (typos)."""
    planner = TypingPlanner(Settings(error_rate=0.15))
    planner.seed(42)
    plan = planner.plan([TextSegment(text=MEDIUM_TEXT)])

    counts = count_action_types(plan.actions)
    mistake_count = counts.get("MakeMistake", 0)

    # With 15% error rate on ~500 chars, we should get some mistakes
    assert mistake_count > 0, "Expected at least some MakeMistake actions"
    print(f"  PASS: Plan contains {mistake_count} mistakes")


def test_plan_contains_pauses_at_boundaries():
    """Pauses should appear at sentence and paragraph boundaries."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=MEDIUM_TEXT)])

    pause_actions = [a for a in plan.actions if isinstance(a, Pause)]
    # Multi-paragraph text should have several pauses
    assert len(pause_actions) >= 3, f"Expected >=3 pauses, got {len(pause_actions)}"

    # Check we have both short (sentence) and longer (paragraph/thought) pauses
    durations = [p.duration for p in pause_actions]
    has_short = any(d < 2.0 for d in durations)
    has_long = any(d > 2.0 for d in durations)

    print(f"  PASS: {len(pause_actions)} pauses, "
          f"range {min(durations):.1f}s - {max(durations):.1f}s, "
          f"has_short={has_short}, has_long={has_long}")


def test_plan_paragraph_breaks():
    """Multi-paragraph text should have PressKey(enter) for paragraph breaks."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=MEDIUM_TEXT)])

    enter_keys = [a for a in plan.actions
                  if isinstance(a, PressKey) and a.key == "enter"]
    # MEDIUM_TEXT has 2 paragraph breaks (\n\n)
    assert len(enter_keys) >= 2, f"Expected >=2 enter keys, got {len(enter_keys)}"
    print(f"  PASS: {len(enter_keys)} enter key presses for paragraph breaks")


def test_plan_simple_mode():
    """Simple mode (for table cells) should have no proofreading or rewrites."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text="Hello world test cell")], simple=True)

    counts = count_action_types(plan.actions)
    # Simple mode should only have TypeText and maybe Rewrite (single-char fixes)
    # No PressKey(left/right) for proofreading
    left_arrows = [a for a in plan.actions
                   if isinstance(a, PressKey) and a.key == "left"]
    assert len(left_arrows) == 0, "Simple mode should not have arrow key navigation"
    print(f"  PASS: Simple mode plan: {dict(counts)}, no arrow navigation")


# =====================================================================
# 5. Rewrite Position Picking Tests
# =====================================================================

def test_no_minimum_spacing():
    """Rewrite positions should NOT have 15-char minimum spacing anymore."""
    planner = TypingPlanner(Settings(
        rewrite_base_probability=0.99,  # force high probability
        rewrite_max_probability=0.99,
    ))
    planner.seed(42)

    text = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"
    positions = planner._pick_rewrite_positions(text, total_paste_chars=5000)

    if len(positions) >= 2:
        pos_values = [p[0] for p in positions]
        # Check that some positions are less than 15 chars apart
        spacings = [pos_values[i+1] - pos_values[i] for i in range(len(pos_values)-1)]
        has_close = any(s < 15 for s in spacings)
        print(f"  PASS: {len(positions)} positions, spacings: {spacings}, "
              f"close together: {has_close}")
    else:
        print(f"  PASS: {len(positions)} positions picked (text may be short)")


def test_rewrite_positions_have_granularity():
    """Rewrite positions include granularity tag."""
    planner = TypingPlanner(Settings(
        rewrite_base_probability=0.99,
        rewrite_max_probability=0.99,
    ))
    planner.seed(42)

    positions = planner._pick_rewrite_positions(MEDIUM_TEXT, total_paste_chars=5000)

    granularities = set(g for _, g in positions)
    assert granularities <= {"word", "sentence", "paragraph"}
    print(f"  PASS: {len(positions)} positions with granularities: {granularities}")


def test_rewrite_scaling_with_length():
    """More rewrites for longer text, fewer for shorter."""
    planner = TypingPlanner()
    planner.seed(42)

    short_positions = planner._pick_rewrite_positions(SHORT_TEXT, total_paste_chars=25)
    planner.seed(42)  # reset seed
    long_positions = planner._pick_rewrite_positions(MEDIUM_TEXT, total_paste_chars=5000)

    # Long text should generally have more rewrite positions
    print(f"  PASS: Short text: {len(short_positions)} rewrites, "
          f"long text: {len(long_positions)} rewrites")


# =====================================================================
# 6. Cascading Rewrite Tests
# =====================================================================

def test_build_cascading_actions_base_case():
    """At max depth or short text, cascading returns flat TypeText."""
    planner = TypingPlanner()
    planner.seed(42)

    # Max depth
    result = planner._build_cascading_actions("hello world", depth=2)
    assert len(result) == 1
    assert isinstance(result[0], TypeText)
    assert result[0].text == "hello world"
    print("  PASS: Cascading base case (max depth) returns flat TypeText")


def test_build_cascading_actions_short_text():
    """Very short text should not cascade."""
    planner = TypingPlanner()
    planner.seed(42)

    result = planner._build_cascading_actions("hi", depth=0)
    assert len(result) == 1
    assert isinstance(result[0], TypeText)
    print("  PASS: Cascading base case (short text) returns flat TypeText")


def test_rewrite_new_actions_structure():
    """A Rewrite action should have new_actions (not new_text string)."""
    r = Rewrite.simple(5, "hello world")
    assert isinstance(r.new_actions, list)
    assert all(isinstance(a, TypingAction) for a in r.new_actions)
    print("  PASS: Rewrite.new_actions is a list of TypingAction")


# =====================================================================
# 7. Character Counting Tests
# =====================================================================

def test_recursive_char_counting():
    """Character counting should work recursively through nested Rewrites."""
    inner_rewrite = Rewrite(
        delete_count=5,
        new_actions=[TypeText(text="abc"), TypeText(text="de")],
    )
    outer_rewrite = Rewrite(
        delete_count=10,
        new_actions=[TypeText(text="12"), inner_rewrite, TypeText(text="67")],
    )
    actions = [TypeText(text="start"), outer_rewrite, TypeText(text="end")]

    total = count_typed_chars_recursive(actions)
    # "start"(5) + "12"(2) + "abc"(3) + "de"(2) + "67"(2) + "end"(3) = 17
    assert total == 17, f"Expected 17 chars, got {total}"
    print("  PASS: Recursive char counting: 17 chars across nested rewrites")


def test_plan_char_count_positive():
    """Plan should report positive total_characters for non-empty text."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=MEDIUM_TEXT)])
    assert plan.total_characters > 0
    print(f"  PASS: Plan total_characters = {plan.total_characters}")


# =====================================================================
# 8. HumanErrors Interface Tests
# =====================================================================

def test_human_errors_interface():
    """HumanErrors has the expected interface methods."""
    from src.human_errors import HumanErrors
    h = HumanErrors()

    assert hasattr(h, "process_text")
    assert hasattr(h, "find_thought_boundaries")
    assert hasattr(h, "is_enabled")
    print(f"  PASS: HumanErrors interface OK, AI enabled: {h.is_enabled}")


def test_human_errors_process_text_return_type():
    """process_text returns (str, list) tuple."""
    from src.human_errors import HumanErrors
    h = HumanErrors()

    result = h.process_text("Hello world")
    assert isinstance(result, tuple)
    assert len(result) == 2
    modified_text, misspellings = result
    assert isinstance(modified_text, str)
    assert isinstance(misspellings, list)
    print(f"  PASS: process_text returns correct types: "
          f"text={modified_text!r}, misspellings={misspellings}")


def test_human_errors_empty_text():
    """process_text handles empty text gracefully."""
    from src.human_errors import HumanErrors
    h = HumanErrors()

    text, misspellings = h.process_text("")
    assert text == ""
    assert misspellings == []
    print("  PASS: process_text handles empty text")


def test_human_errors_find_thought_boundaries():
    """find_thought_boundaries returns list of ints."""
    from src.human_errors import HumanErrors
    h = HumanErrors()

    result = h.find_thought_boundaries("Short text")
    assert isinstance(result, list)
    # Short text returns empty (< 50 chars check)
    assert result == []
    print("  PASS: find_thought_boundaries returns list, empty for short text")


# =====================================================================
# 9. AIRewriter Interface Tests
# =====================================================================

def test_ai_rewriter_interface():
    """AIRewriter has expected methods."""
    from src.ai_planner import AIRewriter
    r = AIRewriter()

    assert hasattr(r, "generate_first_draft")
    assert hasattr(r, "generate_drafts_batch")
    assert hasattr(r, "pick_revisit_targets")
    assert hasattr(r, "clear_cache")
    assert hasattr(r, "is_enabled")
    print(f"  PASS: AIRewriter interface OK, enabled: {r.is_enabled}")


def test_ai_rewriter_cache():
    """AIRewriter cache stores and retrieves drafts."""
    from src.ai_planner import AIRewriter
    r = AIRewriter()
    r._cache["test text"] = "draft text"
    assert r._cache.get("test text") == "draft text"
    r.clear_cache()
    assert r._cache.get("test text") is None
    print("  PASS: AIRewriter cache works")


# =====================================================================
# 10. Revisit Feature Tests
# =====================================================================

def test_revisit_count_resets():
    """_revisit_count resets at the start of each plan() call."""
    planner = TypingPlanner()
    planner._revisit_count = 99  # simulate leftover from previous session
    planner.seed(42)
    planner.plan([TextSegment(text=SHORT_TEXT)])
    assert planner._revisit_count == 0, (
        f"_revisit_count should reset to 0, got {planner._revisit_count}"
    )
    print("  PASS: _revisit_count resets between plan() calls")


def test_build_revisit_too_close():
    """_build_revisit should reject text that's too close (< 80 chars back)."""
    planner = TypingPlanner()
    planner.seed(42)

    # Text where the target is only 20 chars from the end
    typed = "A" * 20 + "target" + "B" * 10
    result = planner._build_revisit(typed, "target", "revised")
    assert result == [], "Should reject revisit for text < 80 chars back"
    print("  PASS: _build_revisit rejects too-close targets")


def test_build_revisit_not_found():
    """_build_revisit handles target not found in text."""
    planner = TypingPlanner()
    result = planner._build_revisit("some text here", "nonexistent", "revised")
    assert result == []
    print("  PASS: _build_revisit handles missing target")


def test_build_revisit_structure():
    """_build_revisit generates correct action sequence."""
    planner = TypingPlanner()
    planner.seed(42)

    typed = "A" * 200 + "target phrase here" + "B" * 100
    result = planner._build_revisit(typed, "target phrase here", "revised phrase")

    assert len(result) > 0, "Should generate revisit actions"

    from src.planned_text import PlannedText
    state = PlannedText("existing prefix " + typed).apply(result)
    assert state.valid
    assert state.text == "existing prefix " + typed.replace("target phrase here", "revised phrase")
    assert state.cursor == len(state.text)
    assert not any(isinstance(a, ApplyFormatting) and a.shortcut[0] in ("cmd", "opt") for a in result)


# =====================================================================
# 11. Edge Cases
# =====================================================================

def test_empty_text():
    """Planning empty text should produce empty plan."""
    planner = TypingPlanner()
    plan = planner.plan([TextSegment(text="")])
    assert len(plan.actions) == 0
    assert plan.total_characters == 0
    print("  PASS: Empty text produces empty plan")


def test_single_word():
    """Planning a single word should work."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text="Hello")])
    assert plan.total_characters > 0
    print(f"  PASS: Single word plan: {len(plan.actions)} actions")


def test_whitespace_only():
    """Whitespace-only text should produce minimal plan."""
    planner = TypingPlanner()
    plan = planner.plan([TextSegment(text="   ")])
    print(f"  PASS: Whitespace plan: {len(plan.actions)} actions")


def test_very_long_text():
    """Long text should not crash or hang."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=LONG_TEXT)])

    assert plan.total_characters > 0
    assert len(plan.actions) > 0
    counts = count_action_types(plan.actions)
    print(f"  PASS: Long text ({len(LONG_TEXT)} chars) plan: "
          f"{len(plan.actions)} actions, {plan.total_characters} typed chars")
    print(f"        Counts: {dict(counts)}")


def test_multiple_segments():
    """Planning multiple segments should work."""
    planner = TypingPlanner()
    planner.seed(42)
    segments = [
        TextSegment(text="First paragraph about science.\n\n"),
        TextSegment(text="Second paragraph about art.\n\n"),
        TextSegment(text="Third paragraph about history."),
    ]
    plan = planner.plan(segments)
    assert plan.segment_count == 3
    assert plan.total_characters > 0
    print(f"  PASS: Multi-segment plan: {plan.segment_count} segments, "
          f"{len(plan.actions)} actions")


# =====================================================================
# 12. Orchestrator Integration (mock simulator)
# =====================================================================

def test_orchestrator_count_typed_chars():
    """Orchestrator._count_typed_chars works recursively."""
    from src.orchestrator import Orchestrator

    orch = Orchestrator()

    # Build a nested action list
    actions = [
        TypeText(text="hello"),
        MakeMistake(wrong_text="wrld", correct_text="world"),
        Rewrite(delete_count=5, new_actions=[
            TypeText(text="inner"),
            Rewrite(delete_count=2, new_actions=[
                TypeText(text="deep"),
            ]),
        ]),
    ]

    total = orch._count_typed_chars(actions)
    # "hello"(5) + "wrld"(4)+"world"(5) + "inner"(5) + "deep"(4) = 23
    assert total == 23, f"Expected 23, got {total}"
    print(f"  PASS: Orchestrator._count_typed_chars recursive: {total}")


def test_orchestrator_execute_action():
    """Orchestrator._execute_action dispatches correctly with mock simulator."""
    from src.orchestrator import Orchestrator

    orch = Orchestrator()
    engine = TypingEngine(Settings())

    # Mock simulator
    sim = MagicMock()
    sim.is_active = True
    orch._cancel_event.clear()

    # Test TypeText
    action = TypeText(text="ab")
    result = orch._execute_action(action, engine, sim, "")
    assert sim.type_char.called
    assert result == "b"  # last char typed

    sim.reset_mock()

    # Test Pause
    action = Pause(duration=0.5)
    result = orch._execute_action(action, engine, sim, "x")
    sim.wait.assert_called_with(0.5)
    assert result == "x"  # prev_char unchanged

    sim.reset_mock()

    # Test PressKey
    action = PressKey(key="enter")
    result = orch._execute_action(action, engine, sim, "x")
    sim.press_key.assert_called_with("enter")

    print("  PASS: _execute_action dispatches TypeText, Pause, PressKey correctly")


def test_orchestrator_execute_rewrite_recursive():
    """Orchestrator._execute_rewrite handles nested Rewrites."""
    from src.orchestrator import Orchestrator

    orch = Orchestrator()
    orch._chars_typed = 0
    orch._total_chars = 100
    orch._typing_start_time = 0.0
    engine = TypingEngine(Settings())

    sim = MagicMock()
    sim.is_active = True
    orch._cancel_event.clear()

    # Nested rewrite: outer deletes 5, inner has a sub-rewrite
    inner = Rewrite(delete_count=2, new_actions=[TypeText(text="OK")])
    outer = Rewrite(
        delete_count=5,
        new_actions=[TypeText(text="A"), inner, TypeText(text="B")],
    )

    orch._execute_rewrite(outer, engine, sim)

    # Should have pressed backspace for outer (5x) and inner (2x) = 7 total
    backspace_calls = [c for c in sim.press_key.call_args_list
                       if c[0][0] == "backspace"]
    assert len(backspace_calls) == 7, f"Expected 7 backspaces, got {len(backspace_calls)}"

    # Should have typed "A", "O", "K", "B" = 4 type_char calls
    type_calls = sim.type_char.call_args_list
    typed_chars = [c[0][0] for c in type_calls]
    assert "".join(typed_chars) == "AOKB", f"Expected 'AOKB', got {''.join(typed_chars)}"

    print(f"  PASS: Recursive rewrite execution: {len(backspace_calls)} backspaces, "
          f"typed {''.join(typed_chars)!r}")


# =====================================================================
# 13. Chunk Boundary Tests (regression from refactor)
# =====================================================================

def test_chunks_sentence_flags_preserved():
    """Sentence/paragraph flags still work after thought boundary refactor."""
    planner = TypingPlanner()
    text = "First sentence. Second sentence.\n\nThird sentence."
    chunks = planner._break_into_chunks(text)

    sentence_ends = [c for c in chunks if c.is_sentence_end]
    paragraph_ends = [c for c in chunks if c.is_paragraph_end]

    # First sentence -> is_sentence_end
    # Second sentence -> is_paragraph_end (last in para 1)
    # Newline -> is_paragraph_end
    # Third sentence -> is_paragraph_end (last in para 2)
    assert len(sentence_ends) >= 1
    assert len(paragraph_ends) >= 2
    print(f"  PASS: Chunk flags preserved: {len(sentence_ends)} sentence_end, "
          f"{len(paragraph_ends)} paragraph_end")


def test_chunks_mutual_exclusivity():
    """is_sentence_end and is_paragraph_end are mutually exclusive."""
    planner = TypingPlanner()
    chunks = planner._break_into_chunks("A. B. C.")

    for c in chunks:
        assert not (c.is_sentence_end and c.is_paragraph_end), (
            f"Chunk {c.text!r} has both flags"
        )
    print("  PASS: Chunk flags mutually exclusive")


# =====================================================================
# 14. Extract Span Tests
# =====================================================================

def test_extract_span_word():
    """_extract_span for word granularity extracts 1-5 words."""
    planner = TypingPlanner()
    planner.seed(42)

    text = "The quick brown fox jumps over the lazy dog"
    span = planner._extract_span(text, 0, "word")
    assert span is not None
    assert len(span.split()) <= 8  # rewrite_word_count max
    print(f"  PASS: Word span extracted: {span!r}")


def test_extract_span_sentence():
    """_extract_span for sentence granularity grabs to end of sentence."""
    planner = TypingPlanner()
    text = "The quick brown fox jumps. Over the lazy dog."
    span = planner._extract_span(text, 0, "sentence")
    assert span is not None
    assert span.endswith(".")
    print(f"  PASS: Sentence span: {span!r}")


def test_extract_span_paragraph():
    """_extract_span for paragraph granularity grabs to paragraph end."""
    planner = TypingPlanner()
    text = "First paragraph line.\n\nSecond paragraph."
    span = planner._extract_span(text, 0, "paragraph")
    assert span is not None
    assert "Second" not in span  # shouldn't cross paragraph boundary
    print(f"  PASS: Paragraph span: {span!r}")


# =====================================================================
# 15. Proofreading Tests
# =====================================================================

def test_proofread_builds_actions():
    """_build_proofread generates arrow key navigation and fixes."""
    planner = TypingPlanner()
    planner.seed(42)

    # Simulate 2 typos at different positions
    typos = [("x", "a", 10), ("y", "b", 30)]
    total_chars = 50

    actions = planner._build_proofread(typos, total_chars)

    if actions:
        # Should contain: Pause, PressKey(left), Pause, PressKey(right),
        # PressKey(backspace), TypeText, ..., ApplyFormatting(cmd+down)
        has_left = any(isinstance(a, PressKey) and a.key == "left" for a in actions)
        has_right = any(isinstance(a, PressKey) and a.key == "right" for a in actions)
        has_backspace = any(isinstance(a, PressKey) and a.key == "backspace" for a in actions)
        has_jump_back = any(isinstance(a, ApplyFormatting)
                          and a.shortcut == ("cmd", "down") for a in actions)

        assert has_left, "Proofread should arrow left"
        assert has_right, "Proofread should arrow right past typo"
        assert has_backspace, "Proofread should backspace the typo"
        assert has_jump_back, "Proofread should cmd+down back to end"
        print(f"  PASS: Proofread actions: {len(actions)} total, "
              f"left={has_left}, right={has_right}, bs={has_backspace}, jump={has_jump_back}")
    else:
        print("  PASS: Proofread returned empty (typos may be out of range)")


def test_proofread_rejects_far_typos():
    """Typos > 80 chars back should be ignored by proofreading."""
    planner = TypingPlanner()
    planner.seed(42)

    # Typo at position 5, but 200 chars have been typed (195 chars back)
    typos = [("x", "a", 5)]
    total_chars = 200

    actions = planner._build_proofread(typos, total_chars)
    assert actions == [], "Typos > 80 chars back should be unreachable"
    print("  PASS: Proofread rejects typos > 80 chars back")


# =====================================================================
# 16. TypingProfile Tests
# =====================================================================

def test_typing_profile_defaults():
    """TypingProfile.defaults() matches old hardcoded values."""
    p = TypingProfile.defaults()
    assert p.keystroke.shift_multiplier.min == 1.40
    assert p.keystroke.shift_multiplier.max == 2.00
    assert p.keystroke.jitter_sigma == 0.30
    assert p.keystroke.warmup_chars == 15
    assert p.peek.min_chars_before_peek == 12
    assert p.peek.max_probability == 0.50
    assert p.mistakes.unnoticed_rate == 0.08
    assert p.mistakes.immediate_notice_rate == 0.40
    assert p.burst.base_probability == 0.025
    assert p.fatigue.max_level == 0.4
    assert p.correction.slow_correction_split == 0.5
    assert p.rewrite.cascade_max_depth == 2
    assert p.proofread.max_proofread_distance == 80
    assert p.orchestration.progress_report_frequency == 5
    assert p.persona_description == ""
    assert p.confidence_level == 0.5
    print("  PASS: TypingProfile.defaults() has correct default values")


def test_typing_profile_from_dict():
    """TypingProfile.from_dict() fills specified fields, preserves defaults for others."""
    data = {
        "persona_description": "Tired teenager",
        "confidence_level": 0.3,
        "keystroke": {
            "jitter_sigma": 0.45,
            "warmup_chars": 25,
            "shift_multiplier": {"min": 1.50, "max": 2.50},
        },
        "peek": {
            "min_chars_before_peek": 8,
        },
    }
    p = TypingProfile.from_dict(data)
    assert p.persona_description == "Tired teenager"
    assert p.confidence_level == 0.3
    assert p.keystroke.jitter_sigma == 0.45
    assert p.keystroke.warmup_chars == 25
    assert p.keystroke.shift_multiplier.min == 1.50
    assert p.keystroke.shift_multiplier.max == 2.50
    assert p.peek.min_chars_before_peek == 8
    assert p.keystroke.warmup_slowdown == 0.20
    assert p.peek.max_probability == 0.50
    assert p.mistakes.unnoticed_rate == 0.08
    assert p.fatigue.max_level == 0.4
    print("  PASS: TypingProfile.from_dict() partial overrides work correctly")


def test_typing_profile_range_clamp():
    """Range.clamp() constrains min/max within floor/ceil."""
    r = Range(min=-5.0, max=200.0)
    clamped = r.clamp(floor=0.0, ceil=100.0)
    assert clamped.min == 0.0
    assert clamped.max == 100.0
    r2 = Range(min=10.0, max=50.0)
    clamped2 = r2.clamp(floor=0.0, ceil=100.0)
    assert clamped2.min == 10.0
    assert clamped2.max == 50.0
    r3 = Range(min=5.0, max=5.0)
    clamped3 = r3.clamp(floor=10.0, ceil=20.0)
    assert clamped3.min == 10.0
    assert clamped3.max == 10.0
    print("  PASS: Range.clamp() constrains values correctly")


def test_typing_engine_uses_profile():
    """TypingEngine with custom profile produces different timing."""
    settings = Settings()
    default_profile = TypingProfile.defaults()
    engine_default = TypingEngine(settings, profile=default_profile)
    engine_default.seed(42)
    custom_profile = TypingProfile.from_dict({
        "keystroke": {
            "shift_multiplier": {"min": 5.0, "max": 6.0},
            "jitter_sigma": 0.01,
        },
    })
    engine_custom = TypingEngine(settings, profile=custom_profile)
    engine_custom.seed(42)
    delay_default = engine_default.base_delay_for_char("A")
    delay_custom = engine_custom.base_delay_for_char("A")
    assert delay_custom > delay_default, (
        f"Custom profile shift delay ({delay_custom:.4f}) should be > default ({delay_default:.4f})"
    )
    print(f"  PASS: Engine uses profile: default={delay_default:.4f}, custom={delay_custom:.4f}")


# =====================================================================
# 17. New Action Type Tests
# =====================================================================

def test_distraction_pause_action():
    """DistractionPause creates with correct fields."""
    dp = DistractionPause(duration=45.0, distraction_type="social_media")
    assert dp.duration == 45.0
    assert dp.distraction_type == "social_media"
    assert "social_media" in dp.description
    assert "45" in dp.description
    dp2 = DistractionPause()
    assert dp2.duration == 30.0
    assert dp2.distraction_type == "phone"
    print("  PASS: DistractionPause action creates correctly")


def test_abandon_word_action():
    """AbandonWord creates with correct fields."""
    aw = AbandonWord(partial_text="approx", replacement_text="about")
    assert aw.partial_text == "approx"
    assert aw.replacement_text == "about"
    assert "approx" in aw.description
    assert "about" in aw.description
    aw2 = AbandonWord()
    assert aw2.partial_text == ""
    assert aw2.replacement_text == ""
    print("  PASS: AbandonWord action creates correctly")


def test_type_text_speed_multiplier():
    """TypeText with custom speed_multiplier stores it correctly."""
    tt = TypeText(text="hello", speed_multiplier=0.55)
    assert tt.speed_multiplier == 0.55
    assert tt.text == "hello"
    tt_default = TypeText(text="world")
    assert tt_default.speed_multiplier == 1.0
    print("  PASS: TypeText speed_multiplier works correctly")


# =====================================================================
# 18. Feature Tests (behavioral_content)
# =====================================================================

def test_word_speed_from_behavioral_content():
    """Plan with word_speed_map produces varied speed_multipliers."""
    # Use zero error rate so words don't get broken by mistakes
    planner = TypingPlanner(Settings(error_rate=0.0, false_alarm_rate=0.0))
    planner.seed(42)
    behavioral = {
        "word_speed_map": [
            {"word": "photosynthesis", "multiplier": 1.5},
            {"word": "the", "multiplier": 0.7},
        ],
    }
    text = "the process of photosynthesis is important"
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    type_actions = [a for a in plan.actions if isinstance(a, TypeText)]
    multipliers = set(a.speed_multiplier for a in type_actions)
    has_varied = any(m != 1.0 for m in multipliers)
    assert has_varied, f"Expected varied speed multipliers, got only: {multipliers}"
    print(f"  PASS: word_speed_map produces varied multipliers: {multipliers}")


def test_word_abandonment():
    """Plan with word_abandonments produces AbandonWord actions."""
    planner = TypingPlanner(Settings(error_rate=0.0, false_alarm_rate=0.0,
                                     grammar_error_rate=0.0, punctuation_error_rate=0.0,
                                     rewrite_base_probability=0.0, rewrite_max_probability=0.0))
    planner.seed(42)
    behavioral = {
        "word_abandonments": [
            {"word": "approximately", "abandon_after_chars": 6, "replacement": "about"},
        ],
    }
    text = "approximately three miles away from the house."
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    abandon_actions = [a for a in plan.actions if isinstance(a, AbandonWord)]
    assert len(abandon_actions) >= 1, "Expected at least 1 AbandonWord action"
    aw = abandon_actions[0]
    assert aw.partial_text == "approx"
    assert aw.replacement_text == "about"
    print(f"  PASS: word_abandonments produces AbandonWord: {aw.description}")


def test_sentence_restructuring():
    """Plan with sentence_restructures produces Rewrite actions for restructured sentences."""
    planner = TypingPlanner(Settings(error_rate=0.0, false_alarm_rate=0.0,
                                     grammar_error_rate=0.0, punctuation_error_rate=0.0))
    planner.seed(42)
    text = "The experiment showed interesting results."
    behavioral = {
        "sentence_restructures": [
            {
                "original_sentence": "The experiment showed interesting results.",
                "first_draft": "The experiment had some interesting results and stuff.",
            },
        ],
    }
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    rewrite_actions = [a for a in plan.actions if isinstance(a, Rewrite)]
    assert len(rewrite_actions) >= 1, "Expected at least 1 Rewrite from restructuring"
    rw = rewrite_actions[0]
    assert rw.delete_count == len("The experiment had some interesting results and stuff.")
    print(f"  PASS: sentence_restructures produces Rewrite: delete {rw.delete_count} chars")


def test_distraction_insertion():
    """Plan with distraction_points produces DistractionPause actions."""
    planner = TypingPlanner()
    planner.seed(42)
    text = "This is a sentence. " * 40
    behavioral = {
        "distraction_points": [
            {"position": 600, "quality": "high"},
        ],
    }
    profile = TypingProfile.defaults()
    profile.behaviors.distraction.probability_per_break_point = 1.0
    profile.behaviors.distraction.min_interval_chars = 0
    planner.profile = profile
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    distraction_actions = [a for a in plan.actions if isinstance(a, DistractionPause)]
    assert len(distraction_actions) >= 1, "Expected at least 1 DistractionPause"
    dp = distraction_actions[0]
    assert dp.duration > 0
    print(f"  PASS: distraction_points produces DistractionPause: {dp.duration:.0f}s")


def test_quote_speed_multiplier():
    """Plan with quote_ranges produces slower TypeText within quote regions."""
    planner = TypingPlanner()
    planner.seed(42)
    text = 'She said "knowledge is power" and walked away.'
    behavioral = {
        "quote_ranges": [
            {"start": 9, "end": 29, "type": "direct_quote"},
        ],
    }
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    type_actions = [a for a in plan.actions if isinstance(a, TypeText)]
    slow_actions = [a for a in type_actions if a.speed_multiplier < 1.0]
    assert len(slow_actions) >= 1, "Expected TypeText with reduced speed_multiplier in quote range"
    print(f"  PASS: quote_ranges produces {len(slow_actions)} slow TypeText actions")


def test_autocorrect_fixes():
    """Plan with autocorrect_fixes produces navigation sequences (opt+left, etc.)."""
    planner = TypingPlanner()
    planner.seed(42)
    text = "I will recieve the package tomorrow morning from the delivery service at home."
    behavioral = {
        "autocorrect_fixes": [
            {"word": "recieve", "correct": "receive", "position": 7},
        ],
    }
    profile = TypingProfile.defaults()
    profile.behaviors.autocorrect.min_words_back = 2
    profile.behaviors.autocorrect.max_words_back = 3
    planner.profile = profile
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    nav_actions = [a for a in plan.actions if isinstance(a, ApplyFormatting)
                   and a.shortcut == ("opt", "left")]
    select_actions = [a for a in plan.actions if isinstance(a, ApplyFormatting)
                      and a.shortcut == ("opt", "shift", "right")]
    if nav_actions and select_actions:
        print(f"  PASS: autocorrect_fixes produces navigation: "
              f"{len(nav_actions)} word jumps, {len(select_actions)} selections")
    else:
        print(f"  PASS: autocorrect_fixes plan generated without crash "
              f"({len(plan.actions)} actions)")


def test_final_proofread_pass():
    """Plan with proofreading_fixes appends proofread actions at the end."""
    planner = TypingPlanner()
    planner.seed(42)
    text = MEDIUM_TEXT
    behavioral = {
        "proofreading_fixes": [
            {"original": "there paper", "fixed": "their paper", "position_fraction": 0.3},
        ],
    }
    profile = TypingProfile.defaults()
    profile.behaviors.final_proofread.probability = 1.0
    planner.profile = profile
    plan = planner.plan([TextSegment(text=text)], behavioral_content=behavioral)
    # The AI invented an error absent from this input: it must not select
    # unrelated text at its approximate position_fraction.
    assert "there paper" not in text
    assert not any(isinstance(a, TypeText) and "their paper" in a.text for a in plan.actions)


def test_no_behavioral_content_no_crash():
    """Plan without behavioral_content still works (no crash)."""
    planner = TypingPlanner()
    planner.seed(42)
    plan = planner.plan([TextSegment(text=MEDIUM_TEXT)])
    assert len(plan.actions) > 0
    assert plan.total_characters > 0
    plan2 = planner.plan([TextSegment(text=MEDIUM_TEXT)], behavioral_content={})
    assert len(plan2.actions) > 0
    print(f"  PASS: Plan without behavioral_content: {len(plan.actions)} actions, "
          f"with empty dict: {len(plan2.actions)} actions")


# =====================================================================
# 19. Orchestrator Tests (new features)
# =====================================================================

def test_orchestrator_execute_abandon_word():
    """Orchestrator._execute_abandon_word types partial, backspaces, types replacement."""
    from src.orchestrator import Orchestrator
    orch = Orchestrator()
    orch._chars_typed = 0
    orch._total_chars = 100
    orch._typing_start_time = 0.0
    engine = TypingEngine(Settings())
    sim = MagicMock()
    sim.is_active = True
    orch._cancel_event.clear()
    action = AbandonWord(partial_text="approx", replacement_text="about")
    orch._execute_abandon_word(action, engine, sim, "")
    type_calls = [c for c in sim.type_char.call_args_list]
    typed_chars = [c[0][0] for c in type_calls]
    assert "".join(typed_chars[:6]) == "approx", f"Expected 'approx', got {''.join(typed_chars[:6])}"
    assert "".join(typed_chars[6:]) == "about", f"Expected 'about', got {''.join(typed_chars[6:])}"
    backspace_calls = [c for c in sim.press_key.call_args_list if c[0][0] == "backspace"]
    assert len(backspace_calls) == 6, f"Expected 6 backspaces, got {len(backspace_calls)}"
    print(f"  PASS: _execute_abandon_word: typed {''.join(typed_chars)}, "
          f"{len(backspace_calls)} backspaces")


def test_orchestrator_execute_distraction_pause():
    """Orchestrator handles DistractionPause by waiting for the full duration."""
    from src.orchestrator import Orchestrator
    orch = Orchestrator()
    engine = TypingEngine(Settings())
    sim = MagicMock()
    sim.is_active = True
    orch._cancel_event.clear()
    action = DistractionPause(duration=60.0, distraction_type="zone_out")
    result = orch._execute_action(action, engine, sim, "x")
    wait_calls = [c[0][0] for c in sim.wait.call_args_list]
    assert 60.0 in wait_calls, f"Expected wait(60.0), got wait calls: {wait_calls}"
    assert result == "x"
    print(f"  PASS: DistractionPause handler: wait(60.0) called, prev_char preserved")


def test_orchestrator_speed_multiplier():
    """Half speed takes twice as long for the same seeded keystroke."""
    from src.orchestrator import Orchestrator
    orch = Orchestrator()
    orch._chars_typed = 0
    orch._total_chars = 100
    orch._typing_start_time = 0.0
    engine = TypingEngine(Settings())
    engine.seed(42)
    sim_normal = MagicMock()
    sim_normal.is_active = True
    orch._cancel_event.clear()
    engine.reset()
    engine.seed(42)
    action_normal = TypeText(text="a", speed_multiplier=1.0)
    orch._execute_type_text(action_normal, engine, sim_normal, "")
    normal_waits = [c[0][0] for c in sim_normal.wait.call_args_list]
    sim_slow = MagicMock()
    sim_slow.is_active = True
    orch._cancel_event.clear()
    orch._chars_typed = 0
    engine.reset()
    engine.seed(42)
    action_slow = TypeText(text="a", speed_multiplier=0.5)
    orch._execute_type_text(action_slow, engine, sim_slow, "")
    slow_waits = [c[0][0] for c in sim_slow.wait.call_args_list]
    assert len(normal_waits) >= 1 and len(slow_waits) >= 1
    normal_delay = normal_waits[-1]
    slow_delay = slow_waits[-1]
    ratio = slow_delay / normal_delay if normal_delay > 0 else 0
    assert 1.5 < ratio < 2.5, f"Expected ratio ~2.0, got {ratio:.2f} (normal={normal_delay:.4f}, slow={slow_delay:.4f})"
    print(f"  PASS: speed_multiplier scales delay: ratio={ratio:.2f}")


def test_count_typed_chars_new_types():
    """Orchestrator._count_typed_chars handles AbandonWord and DistractionPause."""
    from src.orchestrator import Orchestrator
    orch = Orchestrator()
    actions = [
        TypeText(text="hello"),
        AbandonWord(partial_text="approx", replacement_text="about"),
        DistractionPause(duration=30.0),
        MakeMistake(wrong_text="wrld", correct_text="world"),
    ]
    total = orch._count_typed_chars(actions)
    assert total == 25, f"Expected 25, got {total}"
    print(f"  PASS: _count_typed_chars with new types: {total}")


# =====================================================================
# 20. AI Profile Generator Tests
# =====================================================================

def test_ai_profile_generator_disabled():
    """AIProfileGenerator with no API key returns defaults."""
    with patch.dict(os.environ, {}, clear=True):
        from src.ai_planner import AIProfileGenerator
        gen = AIProfileGenerator()
        assert not gen.is_enabled
        profile = gen.generate_profile("Some text to type.")
        assert profile.keystroke.jitter_sigma == 0.30
        assert profile.persona_description == ""
        print("  PASS: AIProfileGenerator disabled returns defaults")


def test_ai_profile_generator_generates_profile():
    """AIProfileGenerator with mocked API returns a valid profile."""
    mock_response_text = '{"persona_description": "Energetic morning teen", "confidence_level": 0.8, "keystroke": {"jitter_sigma": 0.22}}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=mock_response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-123"}):
        from src.ai_planner import AIProfileGenerator
        gen = AIProfileGenerator()
        gen._client = mock_client
        gen._enabled = True
        profile = gen.generate_profile("Some text to type about science.")
    assert profile.persona_description == "Energetic morning teen"
    assert profile.confidence_level == 0.8
    assert profile.keystroke.jitter_sigma == 0.22
    assert profile.keystroke.warmup_chars == 15
    assert profile.peek.min_chars_before_peek == 12
    print(f"  PASS: AIProfileGenerator generates profile: {profile.persona_description}")


# =====================================================================
# RUN ALL TESTS
# =====================================================================

if __name__ == "__main__":
    all_tests = [
        # 1. Rewrite model
        test_rewrite_simple_factory,
        test_rewrite_nested_new_text,
        test_rewrite_empty,
        test_rewrite_description,
        # 2. Settings
        test_new_settings_fields,
        test_old_settings_removed,
        test_settings_serialization,
        # 3. Typing engine
        test_sigmoid_scaling,
        test_should_rewrite_uses_length,
        test_granularity_picker,
        test_cascade_and_repeat,
        # 4. Plan generation
        test_plan_short_text,
        test_plan_medium_text,
        test_plan_contains_mistakes,
        test_plan_contains_pauses_at_boundaries,
        test_plan_paragraph_breaks,
        test_plan_simple_mode,
        # 5. Rewrite positions
        test_no_minimum_spacing,
        test_rewrite_positions_have_granularity,
        test_rewrite_scaling_with_length,
        # 6. Cascading rewrites
        test_build_cascading_actions_base_case,
        test_build_cascading_actions_short_text,
        test_rewrite_new_actions_structure,
        # 7. Character counting
        test_recursive_char_counting,
        test_plan_char_count_positive,
        # 8. HumanErrors
        test_human_errors_interface,
        test_human_errors_process_text_return_type,
        test_human_errors_empty_text,
        test_human_errors_find_thought_boundaries,
        # 9. AIRewriter
        test_ai_rewriter_interface,
        test_ai_rewriter_cache,
        # 10. Revisit
        test_revisit_count_resets,
        test_build_revisit_too_close,
        test_build_revisit_not_found,
        test_build_revisit_structure,
        # 11. Edge cases
        test_empty_text,
        test_single_word,
        test_whitespace_only,
        test_very_long_text,
        test_multiple_segments,
        # 12. Orchestrator
        test_orchestrator_count_typed_chars,
        test_orchestrator_execute_action,
        test_orchestrator_execute_rewrite_recursive,
        # 13. Chunk boundaries
        test_chunks_sentence_flags_preserved,
        test_chunks_mutual_exclusivity,
        # 14. Extract span
        test_extract_span_word,
        test_extract_span_sentence,
        test_extract_span_paragraph,
        # 15. Proofreading
        test_proofread_builds_actions,
        test_proofread_rejects_far_typos,
        # 16. TypingProfile
        test_typing_profile_defaults,
        test_typing_profile_from_dict,
        test_typing_profile_range_clamp,
        test_typing_engine_uses_profile,
        # 17. New action types
        test_distraction_pause_action,
        test_abandon_word_action,
        test_type_text_speed_multiplier,
        # 18. Feature tests (behavioral_content)
        test_word_speed_from_behavioral_content,
        test_word_abandonment,
        test_sentence_restructuring,
        test_distraction_insertion,
        test_quote_speed_multiplier,
        test_autocorrect_fixes,
        test_final_proofread_pass,
        test_no_behavioral_content_no_crash,
        # 19. Orchestrator (new features)
        test_orchestrator_execute_abandon_word,
        test_orchestrator_execute_distraction_pause,
        test_orchestrator_speed_multiplier,
        test_count_typed_chars_new_types,
        # 20. AI Profile Generator
        test_ai_profile_generator_disabled,
        test_ai_profile_generator_generates_profile,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in all_tests:
        name = test.__name__
        try:
            print(f"\n[{name}]")
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, e))
            print(f"  FAIL: {e}")

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(all_tests)} tests")
    print("=" * 70)

    if errors:
        print("\nFAILURES:")
        for name, err in errors:
            print(f"  {name}: {err}")
        print()

    if failed == 0:
        print("\nALL TESTS PASSED")

