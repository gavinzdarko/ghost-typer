from test_core_browser_capture import pytestmark, run


def test_freeform_blocks_unmeasured_paste_and_drop_without_starting_recording():
    run('freeform.html', """
for (const event of ['paste', 'drop']) {
  let prevented = false;
  element('typing-area').listeners[event]({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
}
assert.equal(started, false);
assert.equal(charCount, 0);
key('typing-area', 'a', 200);
assert.equal(charCount, 1);
""")
