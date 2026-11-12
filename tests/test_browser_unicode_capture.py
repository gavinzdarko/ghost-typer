"""Capture complete Unicode code points without inventing IME timings."""
from test_core_browser_capture import pytestmark, run
import pytest


@pytest.mark.parametrize("page,input_id,counter,intervals", [
    ("index.html", "typing-input", "totalKeystrokes", "ikiValues"),
    ("freeform.html", "typing-area", "charCount", "ikis"),
])
def test_supplementary_keys_preserve_character_counts_and_adjacent_timings(
        page, input_id, counter, intervals):
    run(page, f"""
key('{input_id}', '𐐀', 100);
assert.equal(started, true);
key('{input_id}', 'a', 200);
key('{input_id}', '😀', 350);
key('{input_id}', 'b', 550);
assert.equal({counter}, 4);
assert.deepEqual({intervals}, [100, 150, 200]);
""")


def test_prompt_render_completion_and_backspace_use_complete_code_points():
    run("index.html", """
PROMPTS.splice(0, PROMPTS.length, 'a𐐀😀b');
init();
assert.deepEqual(promptChars, ['a', '𐐀', '😀', 'b']);
assert.equal((element('prompt-display').innerHTML.match(/<span /g) || []).length, 4);
key('typing-input', 'a', 100);
key('typing-input', '😀', 200); // mistaken supplementary character
key('typing-input', 'Backspace', 300);
assert.equal(cursorPos, 1);
assert.deepEqual(corrections, [{charsBeforeNoticing: 0, pos: 1}]);
key('typing-input', '𐐀', 400);
key('typing-input', '😀', 500);
assert.equal(finished, false);
showSummary = () => {};
key('typing-input', 'b', 600);
assert.equal(finished, true);
assert.equal(cursorPos, 4);
assert.equal(typed.join(''), 'a𐐀😀b');
assert.deepEqual(keystrokes.filter(k => k.key !== 'Backspace').map(k => k.correct),
                 [true, false, true, true, true]);
""")


def test_supplementary_key_can_focus_an_unstarted_prompt():
    run("index.html", """
let focused = 0;
element('typing-input').focus = () => focused++;
document.listeners.keydown({key: '𐐀'});
assert.equal(focused, 1);
document.listeners.keydown({key: 'ArrowLeft'});
document.listeners.keydown({key: '😀', isComposing: true});
document.listeners.keydown({key: '😀', metaKey: true});
document.listeners.keydown({key: '👩‍💻'});
assert.equal(focused, 1);
""")


@pytest.mark.parametrize("page,input_id,counter,intervals", [
    ("index.html", "typing-input", "totalKeystrokes", "ikiValues"),
    ("freeform.html", "typing-area", "charCount", "ikis"),
])
def test_composition_and_multi_code_point_keys_remain_unmeasured_boundaries(
        page, input_id, counter, intervals):
    run(page, f"""
key('{input_id}', 'a', 100);
key('{input_id}', '😀', 200, {{isComposing: true}});
key('{input_id}', 'b', 300);
key('{input_id}', '👩‍💻', 400); // multiple code points, no individual key timing
key('{input_id}', '𐐀', 500);
key('{input_id}', 'Dead', 600);
key('{input_id}', 'c', 700);
assert.equal({counter}, 4);
assert.deepEqual({intervals}, []);
""")
