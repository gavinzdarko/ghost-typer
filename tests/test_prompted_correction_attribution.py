from test_core_browser_capture import run


def test_deleting_correct_suffix_keeps_error_pending_until_removed():
    run('index.html', '''
promptText = 'abc def ghi'; promptChars = promptText.split('');
for (const [i, char] of Array.from('xbc ').entries()) key('typing-input', char, 100 + i * 100);
key('typing-input', 'Backspace', 500);
assert.equal(typed.join(''), 'xbc');
assert.deepEqual(corrections, []);
assert.ok(errorsAtPos[0]);
// Stop deleting, retype the space, and only later remove the actual error.
key('typing-input', ' ', 600);
for (let i = 0; i < 4; i++) key('typing-input', 'Backspace', 700 + i * 100);
assert.deepEqual(corrections, [{charsBeforeNoticing: 3, pos: 0}]);
assert.deepEqual(errorsAtPos, {});
''')


def test_multiple_outstanding_errors_keep_their_own_notice_distance():
    run('index.html', '''
promptText = 'abc def ghi'; promptChars = promptText.split('');
for (const [i, char] of Array.from('xyc').entries()) key('typing-input', char, 100 + i * 100);
key('typing-input', 'Backspace', 400);
assert.deepEqual(corrections, []);
key('typing-input', 'Backspace', 500);
key('typing-input', 'Backspace', 600);
assert.deepEqual(corrections, [
  {charsBeforeNoticing: 1, pos: 1},
  {charsBeforeNoticing: 2, pos: 0},
]);
assert.deepEqual(errorsAtPos, {});
''')


def test_immediate_correction_and_round_reset():
    run('index.html', '''
promptText = 'abc def ghi'; promptChars = promptText.split('');
key('typing-input', 'x', 100);
key('typing-input', 'Backspace', 200);
assert.deepEqual(corrections, [{charsBeforeNoticing: 0, pos: 0}]);
key('typing-input', 'x', 300);
assert.ok(errorsAtPos[0]);
init();
assert.deepEqual(corrections, []);
assert.deepEqual(errorsAtPos, {});
''')
