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


def test_deletion_sequences_and_key_counts_are_distinct_from_corrected_errors():
    run('index.html', '''
promptText = 'abc def ghi'; promptChars = promptText.split('');
for (const [i, char] of Array.from('xyc').entries()) key('typing-input', char, 100 + i * 100);
for (let i = 0; i < 3; i++) key('typing-input', 'Backspace', 400 + i * 100);
let data = buildConfigJSON().measured_data;
assert.equal(data.corrections, 2);
assert.equal(data.backspace.total_sequences, 1);
assert.equal(data.backspace.total_backspaces, 3);
showSummary();
assert.ok(element('backspace-table').innerHTML.includes('<td>Total Backspaces</td><td>3</td>'));
assert.ok(element('backspace-table').innerHTML.includes('<td>Consecutive BS Sequences</td><td>1</td>'));
// Deleting a correct character is another sequence, but not a corrected error.
key('typing-input', 'a', 800);
key('typing-input', 'Backspace', 900);
data = buildConfigJSON().measured_data;
assert.equal(data.corrections, 2);
assert.equal(data.backspace.total_sequences, 2);
assert.equal(data.backspace.total_backspaces, 4);
init();
data = buildConfigJSON().measured_data;
assert.equal(data.backspace.total_sequences, 0);
assert.equal(data.backspace.total_backspaces, 0);
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
