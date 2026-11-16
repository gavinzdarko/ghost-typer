"""The key that focuses the prompted collector is itself a typing sample."""
import json

from test_core_browser_capture import pytestmark, run

import pytest


@pytest.mark.parametrize('text', ['a', ' ', 'é', '💡'])
def test_unfocused_first_text_key_is_captured_once(text):
    run('index.html', f'''
let focusCalls = 0;
typingInput.focus = () => focusCalls++;
const target = {{closest() {{ return null; }} }};
const first = {{key: {json.dumps(text)}, target, defaultPrevented: false,
  preventDefault() {{ this.defaultPrevented = true; }} }};
now = 100;
document.listeners.keydown(first);
assert.equal(started, true);
assert.equal(startTime, 100);
assert.equal(cursorPos, 1);
assert.deepEqual(typed, [{json.dumps(text)}]);
assert.equal(totalKeystrokes, 1);
assert.equal(first.defaultPrevented, true);
assert.equal(focusCalls, 1);
// A later key targets the focused input and bubbles to document afterward.
const next = {{key: 'b', target: typingInput, defaultPrevented: false,
  preventDefault() {{ this.defaultPrevented = true; }} }};
now = 200;
typingInput.listeners.keydown(next);
document.listeners.keydown(next);
assert.equal(totalKeystrokes, 2);
assert.equal(cursorPos, 2);
assert.deepEqual(ikiValues, [100]);
assert.equal(focusCalls, 1);
''')


@pytest.mark.parametrize('options', [
    "key: 'a', ctrlKey: true", "key: 'a', metaKey: true",
    "key: 'a', isComposing: true", "key: 'a', defaultPrevented: true",
    "key: 'Shift'", "key: 'Enter'", "key: 'ArrowLeft'", "key: 'Backspace'",
])
def test_unfocused_shortcuts_and_nontext_keys_do_not_start(options):
    run('index.html', f'''
let focusCalls = 0;
typingInput.focus = () => focusCalls++;
document.listeners.keydown({{{options}, target: {{closest() {{ return null; }} }},
  preventDefault() {{ throw new Error('Ignored keys must retain default behavior'); }} }});
assert.equal(started, false);
assert.equal(totalKeystrokes, 0);
assert.equal(focusCalls, 0);
''')


def test_start_key_preserves_interactive_controls_and_finished_results():
    run('index.html', '''
let focusCalls = 0;
typingInput.focus = () => focusCalls++;
for (const keyName of ['a', ' ']) {
  const target = {closest(selector) {
    assert.match(selector, /button/);
    assert.match(selector, /input/);
    assert.match(selector, /textarea/);
    assert.match(selector, /select/);
    assert.match(selector, /contenteditable/);
    return this;
  }};
  document.listeners.keydown({key: keyName, target,
    preventDefault() { throw new Error('Control key was intercepted'); }});
}
assert.equal(started, false);
assert.equal(totalKeystrokes, 0);
assert.equal(focusCalls, 0);
finished = true;
document.listeners.keydown({key: 'a', target: {closest() { return null; }},
  preventDefault() { throw new Error('Finished results were changed'); }});
assert.equal(totalKeystrokes, 0);
assert.equal(focusCalls, 0);
''')
