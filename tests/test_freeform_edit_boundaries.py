from test_core_browser_capture import pytestmark, run


def test_freeform_navigation_breaks_digraph_burst_and_backspace_runs():
    run('freeform.html', """
key('typing-area', 'a', 100);
key('typing-area', 'b', 200);
key('typing-area', 'c', 300);
key('typing-area', 'ArrowLeft', 350);
key('typing-area', 'd', 400);
assert.equal(digraphs.cd, undefined);
assert.deepEqual(currentBurst, []);
assert.deepEqual(ikis, [100, 100]);
key('typing-area', 'e', 500);
assert.deepEqual(digraphs.de, [100]);
key('typing-area', 'Backspace', 600);
key('typing-area', 'ArrowLeft', 650);
key('typing-area', 'Backspace', 700);
assert.deepEqual(bsIkis, []);
key('typing-area', 'Backspace', 800);
assert.deepEqual(bsIkis, [100]);
""")


def test_pointer_and_focus_changes_break_runs_but_keep_recorded_samples():
    run('freeform.html', """
for (const event of ['pointerdown', 'blur', 'compositionstart']) {
  reset();
  key('typing-area', 'a', 100);
  key('typing-area', 'b', 200);
  key('typing-area', 'c', 300);
  key('typing-area', 'd', 400);
  area.listeners[event]({});
  key('typing-area', 'e', 500);
  assert.equal(digraphs.de, undefined);
  assert.equal(bursts.length, 1);
  assert.deepEqual(currentBurst, []);
  assert.deepEqual(ikis, [100, 100, 100]);
}
""")


def test_shortcuts_and_composing_keys_break_runs_without_becoming_samples():
    run('freeform.html', """
for (const [name, options] of [
  ['a', {metaKey: true}], ['a', {ctrlKey: true}],
  ['Process', {isComposing: true}], ['Delete', {}], ['Tab', {}]
]) {
  reset();
  key('typing-area', 'a', 100);
  key('typing-area', name, 150, options);
  key('typing-area', 'b', 200);
  assert.equal(charCount, 2);
  assert.equal(digraphs.ab, undefined);
  assert.deepEqual(ikis, []);
}
// Shift changes the next character's case without editing or moving the caret.
reset();
key('typing-area', 'a', 100);
key('typing-area', 'Shift', 150);
key('typing-area', 'B', 200);
assert.deepEqual(digraphs.ab, [100]);
""")
