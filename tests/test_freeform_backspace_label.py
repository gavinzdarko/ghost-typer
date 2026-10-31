from test_core_browser_capture import run


def test_three_backspaces_report_two_intervals_with_an_accurate_label():
    run('freeform.html', """
key('typing-area', 'a', 100);
key('typing-area', 'b', 200);
key('typing-area', 'c', 300);
key('typing-area', 'Backspace', 400);
key('typing-area', 'Backspace', 500);
key('typing-area', 'Backspace', 600);
showResults();
assert.equal(bsCount, 3);
assert.equal(bsIkis.length, 2);
assert.ok(element('t-bs').innerHTML.includes('<td>Consecutive BS intervals</td><td>2</td>'));
""")
