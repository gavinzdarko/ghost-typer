from test_core_browser_capture import run


def test_prompt_digraph_uses_actual_keys_even_when_the_first_key_is_wrong():
    run('index.html', """
promptChars = ['t', 'h', 'e', ' '];
key('typing-input', 'x', 100);
key('typing-input', 'h', 220);
assert.deepEqual(digraphTimings.xh, [120]);
assert.equal(digraphTimings.th, undefined);
key('typing-input', 'Backspace', 320);
key('typing-input', 'h', 420);
assert.deepEqual(digraphTimings.xh, [120]);
""")
