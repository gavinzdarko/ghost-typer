from test_core_browser_capture import run


def test_keystroke_capture_does_not_rescan_the_document():
    run('freeform.html', """
const text = 'word😀 '.repeat(20000);
element('typing-area').value = text;
let characterScans = 0, wordScans = 0;
const originalFrom = Array.from;
Array.from = function(value, ...args) {
  if (value === text) characterScans++;
  return originalFrom.call(this, value, ...args);
};
const originalSplit = String.prototype.split;
String.prototype.split = function(...args) {
  if (String(this) === text.trim()) wordScans++;
  return originalSplit.apply(this, args);
};
for (let i = 0; i < 200; i++) key('typing-area', 'a', 100 + i * 100);
assert.equal(characterScans, 0, 'Character counting must stay off the keydown path');
assert.equal(wordScans, 0, 'Word counting must stay off the keydown path');
assert.equal(element('s-chars').textContent, 200);
assert.equal(element('s-iki').textContent, 100);
now = 60100;
updateLive(); // The existing 500 ms timer refreshes text after browser edits.
assert.equal(characterScans, 1);
assert.equal(wordScans, 1);
assert.equal(element('s-words').textContent, 20000);
assert.equal(element('s-wpm').textContent, 24000); // 120,000 code points / 5.
""")


def test_text_refresh_results_and_reset_keep_unicode_and_edit_counts_correct():
    run('freeform.html', """
key('typing-area', 'a', 100);
element('typing-area').value = 'a😀 b';
now = 60100;
updateLive();
assert.equal(element('s-wpm').textContent, 1);
assert.equal(element('s-words').textContent, 2);
key('typing-area', 'Backspace', 60200);
element('typing-area').value = 'a😀'; // Browser default editing follows keydown.
updateLive();
assert.equal(element('s-words').textContent, 1);
element('typing-area').value = 'one two three';
showResults(); // Finishing must flush text metrics before the next timer tick.
assert.equal(element('s-words').textContent, 3);
assert.equal(buildJSON().words, 3);
assert.equal(element('s-wpm').textContent, buildJSON().wpm);
reset();
assert.equal(element('s-wpm').textContent, 0);
assert.equal(element('s-words').textContent, 0);
key('typing-area', 'z', 70000);
assert.equal(element('s-words').textContent, 0);
""")
