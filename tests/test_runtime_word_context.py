from threading import Event
from unittest.mock import Mock

from orchestrator_support import Orchestrator
from src.models import AbandonWord, MakeMistake, PressKey, Rewrite, TypeText, TypingProfile
from src.typing_engine import TypingEngine


def runtime():
    app = Orchestrator.__new__(Orchestrator)
    app._cancel_event = Event()
    app._profile = TypingProfile.defaults()
    app._chars_typed = 0
    app._total_chars = 100
    app.on_progress = None
    return app, TypingEngine(), Mock(is_active=True)


def test_mistake_retyping_uses_visible_word_and_preserves_physical_count():
    app, engine, sim = runtime()
    app._execute_type_text(TypeText(text='a '), engine, sim, '')
    app._execute_mistake(MakeMistake(wrong_text='teh', correct_text='the'), engine, sim, ' ')
    assert engine.state.current_word == 'the'
    assert engine.state.chars_typed == 8


def test_rewrite_across_word_boundary_restores_preceding_word():
    app, engine, sim = runtime()
    app._execute_type_text(TypeText(text='old word'), engine, sim, '')
    app._execute_rewrite(Rewrite.simple(5, 'er'), engine, sim)
    assert engine.state.current_word == 'older'


def test_abandoned_word_and_standalone_backspace_update_context():
    app, engine, sim = runtime()
    app._execute_abandon_word(AbandonWord(partial_text='part', replacement_text='final'), engine, sim, '')
    assert engine.state.current_word == 'final'
    app._execute_press_key(PressKey(key='backspace'), engine, sim, 'l')
    assert engine.state.current_word == 'fina'
    assert app._execute_press_key(PressKey(key='left'), engine, sim, 'a') == ''
    assert engine.state.current_word == ''


def test_long_unbroken_text_has_bounded_runtime_word_context():
    engine = TypingEngine()
    for char in 'a' * 10000:
        engine.on_char_typed(char)
    assert len(engine.state.current_word) <= 256
    assert len(engine._visible_context) <= 256
    engine.reset()
    assert engine.state.current_word == ''
    assert not engine._visible_context


def test_rewrite_replacement_timing_uses_surviving_visible_character():
    app, engine, sim = runtime()
    app._execute_type_text(TypeText(text='old word'), engine, sim, '')
    engine.delay_for_keystroke = Mock(return_value=0)
    app._execute_rewrite(Rewrite.simple(5, 'er'), engine, sim)
    assert engine.delay_for_keystroke.call_args_list[0].args == ('e', 'd')


def test_abandonment_replacement_timing_forgets_deleted_partial_character():
    app, engine, sim = runtime()
    app._execute_type_text(TypeText(text='t'), engine, sim, '')
    engine.delay_for_keystroke = Mock(return_value=0)
    app._execute_abandon_word(AbandonWord(partial_text='xy', replacement_text='he'), engine, sim, 't')
    assert [call.args for call in engine.delay_for_keystroke.call_args_list] == [
        ('x', 't'), ('y', 'x'), ('h', 't'), ('e', 'h')]


def test_backspace_returns_surviving_character_for_next_action_timing():
    app, engine, sim = runtime()
    app._execute_type_text(TypeText(text='thx'), engine, sim, '')
    previous = app._execute_press_key(PressKey(key='backspace'), engine, sim, 'x')
    engine.delay_for_keystroke = Mock(return_value=0)
    app._execute_type_text(TypeText(text='e'), engine, sim, previous)
    engine.delay_for_keystroke.assert_called_once_with('e', 'h')
