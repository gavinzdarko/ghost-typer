import pytest

from typing_profiler import KeyEvent, TypingAnalyzer
from test_core_browser_capture import run


def pauses(text, pause_before):
    events = []
    now = 0
    for index, char in enumerate(text):
        now += 2 if index == pause_before else .1
        events.append(KeyEvent(now, char, is_space=char == ' ', is_enter=char == '\n',
                               is_backspace=char == '<BS>'))
    analyzer = TypingAnalyzer(events)
    analyzer._detect_pauses()
    return analyzer.pauses


@pytest.mark.parametrize('text,index,context', [
    ('Done. Next', 6, 'sentence'),
    ('Done.  Next', 7, 'sentence'),
    ('"Done." Next', 8, 'sentence'),
    ('word next', 5, 'word_boundary'),
    ('Done. New word', 10, 'word_boundary'),
    ('Done.\n  Next', 8, 'paragraph'),
    ('a.b', 2, 'mid_word'),
])
def test_native_pause_uses_effective_separator_context(text, index, context):
    result = pauses(text, index)
    assert len(result) == 1
    assert result[0].context == context


def test_native_correction_breaks_stale_sentence_context():
    chars = ['D', '.', ' ', '<BS>', ' ', 'N']
    events = [KeyEvent(i * .1, char, is_space=char == ' ', is_backspace=char == '<BS>')
              for i, char in enumerate(chars)]
    events[-1].timestamp += 2
    analyzer = TypingAnalyzer(events)
    analyzer._detect_pauses()
    assert len(analyzer.pauses) == 1
    assert analyzer.pauses[0].context == 'word_boundary'


def test_sentence_settings_use_measured_after_space_pause():
    text = 'Done. Next ordinary words here '
    events = []
    now = 0
    for index, char in enumerate(text):
        now += 4 if index == 6 else .1
        events.append(KeyEvent(now, char, is_space=char == ' '))
    profile = TypingAnalyzer(events).analyze()
    settings = profile['ghost_typer_settings']
    assert settings['sentence_pause_min'] == settings['sentence_pause_max'] == 4
    assert profile['analysis']['sentence_pause_count'] == 1
    assert profile['analysis']['paragraph_pause_count'] == 0


def test_prompted_browser_classifies_after_space_and_preserves_word_pauses():
    run('index.html', r'''
promptText = 'Done. Next word later'; promptChars = promptText.split('');
let stamp = 100;
for (const char of 'Done. ') { key('typing-input', char, stamp); stamp += 100; }
key('typing-input', 'N', stamp + 2000);
assert.equal(pauses.at(-1).context, 'after-sentence');
for (const char of 'ext ') { stamp += 100; key('typing-input', char, stamp + 2000); }
key('typing-input', 'w', stamp + 4000);
assert.equal(pauses.at(-1).context, 'word-start');
assert.equal(buildConfigJSON().measured_data.pauses.after_sentence, 1);
''')
