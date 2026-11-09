"""Word-deletion shortcuts are edits, not one-character corrections."""
from unittest.mock import Mock

import pytest

import typing_profiler as native
from test_core_browser_capture import NODE, run


@pytest.mark.parametrize('option', [native.keyboard.Key.alt_l, native.keyboard.Key.alt_r])
def test_native_option_backspace_does_not_train_character_corrections(monkeypatch, option):
    monkeypatch.setattr(native.time, 'monotonic', Mock(side_effect=[1 + i / 10 for i in range(20)]))
    recorder = native.TypingRecorder()
    for char in 'word':
        recorder._on_press(native.keyboard.KeyCode.from_char(char))
    recorder._on_press(option)
    recorder._on_press(native.keyboard.Key.backspace)
    recorder._on_release(option)
    recorder._on_press(native.keyboard.KeyCode.from_char('a'))
    recorder._on_press(native.keyboard.Key.backspace)
    analyzer = native.TypingAnalyzer(recorder.events)
    analyzer._compute_intervals()
    analyzer._detect_corrections()
    assert [event.char for event in recorder.events] == list('worda') + ['<BS>']
    assert recorder.events[4].run_id != recorder.events[3].run_id
    assert len(analyzer.corrections) == 1
    assert analyzer.corrections[0].chars_deleted == 1
    assert set(analyzer.digraph_intervals) == {'wo', 'or', 'rd'}


def test_native_option_printable_characters_keep_their_timing(monkeypatch):
    monkeypatch.setattr(native.time, 'monotonic', Mock(side_effect=[1, 1.1, 1.2, 1.3]))
    recorder = native.TypingRecorder()
    recorder._on_press(native.keyboard.KeyCode.from_char('a'))
    recorder._on_press(native.keyboard.Key.alt)
    recorder._on_press(native.keyboard.KeyCode.from_char('ø'))
    recorder._on_release(native.keyboard.Key.alt)
    recorder._on_press(native.keyboard.KeyCode.from_char('b'))
    assert [event.char for event in recorder.events] == ['a', 'ø', 'b']
    assert len({event.run_id for event in recorder.events}) == 1


@pytest.mark.skipif(NODE is None, reason='Node is needed for browser capture regressions')
@pytest.mark.parametrize('page,input_id,counter,intervals,bs_intervals', [
    ('index.html', 'typing-input', 'totalKeystrokes', 'ikiValues', 'backspaceTimings'),
    ('freeform.html', 'typing-area', 'charCount', 'ikis', 'bsIkis'),
])
def test_browser_option_deletion_breaks_runs_but_option_printable_text_remains(page, input_id, counter, intervals, bs_intervals):
    run(page, f"""
key('{input_id}', 'a', 100);
key('{input_id}', 'b', 200);
key('{input_id}', 'c', 300);
key('{input_id}', 'Backspace', 400, {{altKey: true}});
assert.equal({counter}, 3);
key('{input_id}', 'ø', 500, {{altKey: true}});
assert.equal({counter}, 4);
assert.deepEqual({intervals}, [100, 100]);
key('{input_id}', 'Backspace', 600);
key('{input_id}', 'Backspace', 700, {{altKey: true}});
key('{input_id}', 'Backspace', 800);
assert.deepEqual({bs_intervals}, []);
""")
