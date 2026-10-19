from test_core_browser_capture import pytestmark, run


def test_prompt_correction_does_not_combine_subthreshold_typing_runs():
    run("index.html", """
key('typing-input', 'a', 100);
key('typing-input', 'b', 200);
key('typing-input', 'c', 300);
key('typing-input', 'Backspace', 3000);
key('typing-input', 'd', 4000);
key('typing-input', 'e', 4100);
showSummary = () => {};
now = 4200;
finish();
assert.deepEqual(ikiValues, [100, 100, 100]);
assert.deepEqual(bursts, []);
""")


def test_prompt_correction_flushes_a_real_burst_once():
    run("index.html", """
key('typing-input', 'a', 100);
key('typing-input', 'b', 200);
key('typing-input', 'c', 300);
key('typing-input', 'd', 400);
key('typing-input', 'Backspace', 3000);
key('typing-input', 'Backspace', 3100);
assert.deepEqual(bursts, [{length: 3, avgIki: 100}]);
assert.deepEqual(currentBurstIkis, []);
key('typing-input', 'e', 4000);
showSummary = () => {};
now = 4200;
finish();
assert.deepEqual(bursts, [{length: 3, avgIki: 100}]);
""")
