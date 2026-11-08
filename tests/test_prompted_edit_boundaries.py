from test_core_browser_capture import pytestmark, run


def test_prompted_interruptions_break_timing_without_erasing_samples():
    run('index.html', '''
for (const [keyName, options] of [
  ['ArrowLeft', {}], ['Delete', {}], ['Tab', {}],
  ['a', {metaKey: true}], ['v', {ctrlKey: true}],
  ['Process', {isComposing: true}]
]) {
  init();
  key('typing-input', 'a', 100);
  key('typing-input', 'b', 200);
  key('typing-input', keyName, 250, options);
  key('typing-input', 'c', 300);
  assert.deepEqual(ikiValues, [100]);
  assert.equal(digraphTimings.bc, undefined);
  assert.deepEqual(currentBurstIkis, []);
  assert.equal(totalKeystrokes, 3);
  key('typing-input', 'd', 400);
  assert.deepEqual(digraphTimings.cd, [100]);
}
''')


def test_prompted_focus_and_composition_end_bursts_and_backspace_sequences():
    run('index.html', '''
for (const event of ['blur', 'pointerdown', 'compositionstart']) {
  init();
  for (const [i, ch] of Array.from('abcd').entries()) key('typing-input', ch, 100 + i * 100);
  typingInput.listeners[event]({});
  assert.equal(bursts.length, 1);
  key('typing-input', 'e', 2500);
  assert.equal(digraphTimings.de, undefined);
  assert.deepEqual(pauses, []);
  key('typing-input', 'Backspace', 2600);
  typingInput.listeners[event]({});
  key('typing-input', 'Backspace', 2700);
  assert.deepEqual(backspaceTimings, []);
  assert.equal(backspaceSequences, 2);
  key('typing-input', 'Backspace', 2800);
  assert.deepEqual(backspaceTimings, [100]);
}
''')


def test_prompted_modifiers_preserve_runs_and_interruptions_do_not_start_session():
    run('index.html', '''
key('typing-input', 'ArrowLeft', 100);
typingInput.listeners.blur({});
assert.equal(started, false);
key('typing-input', 'a', 200);
for (const [i, name] of ['Shift', 'Alt', 'CapsLock'].entries()) key('typing-input', name, 210 + i);
key('typing-input', 'B', 300);
assert.deepEqual(digraphTimings.ab, [100]);
''')
