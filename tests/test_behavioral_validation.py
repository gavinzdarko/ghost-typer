import json
from types import SimpleNamespace
from unittest.mock import Mock
from src.ai_planner import AIProfileGenerator
from src.models import Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner, validate_behavioral_content


BAD_DATA = {
    'word_abandonments': [{'word': 'example', 'abandon_after_chars': 'three', 'replacement': 2}],
    'word_speed_map': [None, {'word': ['bad'], 'multiplier': 2}],
    'word_difficulty_ratings': [{'word': 'example', 'difficulty': 'hard'}],
    'composition_annotations': [{'start': None, 'end': 50, 'mode': 'composition'}],
    'syllable_boundaries': [{'word': 'example', 'syllables': [None, 2]}],
    'quote_ranges': 'not a list',
    'autocorrect_fixes': [False, {'word': 'example', 'correct': 9}],
    'sentence_restructures': [None],
    'proofreading_fixes': 3,
    'distraction_points': [{'position': float('inf')}],
}


def test_malformed_optional_annotations_cannot_abort_paste():
    text = 'A simple example with enough ordinary text. '
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
                                     punctuation_error_rate=0, false_alarm_rate=0,
                                     rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    plan = planner.plan([TextSegment(text)], behavioral_content=BAD_DATA)
    assert PlannedText().apply(plan.actions).text == text
    assert planner._behavioral_content == {}


def test_ai_boundary_filters_bad_entries_and_retains_valid_annotations():
    data = {**BAD_DATA, 'word_speed_map': [None, {'word': 'example', 'multiplier': 1.5}]}
    generator = AIProfileGenerator(enabled=False)
    generator._enabled = True
    generator._client = Mock()
    generator._client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(data))])
    assert generator.generate_behavioral_content('example') == {
        'word_speed_map': [{'word': 'example', 'multiplier': 1.5}]}


def test_annotations_are_bounded_and_syllables_must_match_source_word():
    data = {'word_speed_map': [{'word': 'example', 'multiplier': 1.5}] * 1000,
            'syllable_boundaries': [{'word': 'example', 'syllables': ['wrong', 'word']}],
            'quote_ranges': [{'start': 0, 'end': 5000}]}
    valid = validate_behavioral_content(data, 'example')
    assert len(valid['word_speed_map']) == 100
    assert 'syllable_boundaries' not in valid and 'quote_ranges' not in valid
