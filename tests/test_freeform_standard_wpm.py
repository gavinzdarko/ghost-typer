from test_core_browser_capture import run


def test_freeform_wpm_uses_five_character_units_in_live_results_and_exports():
    run('freeform.html', """
key('typing-area', 'a', 100);
element('typing-area').value = 'abcdefghijklmnopqrst';
now = 60100;
updateLive();
assert.equal(element('s-wpm').textContent, 4);
assert.equal(buildJSON().wpm, 4);
showResults();
assert.match(element('t-overview').innerHTML, /<td>WPM<\\/td><td>4<\\/td>/);
assert.match(element('t-config').innerHTML, /<td>wpm<\\/td><td>4<\\/td>/);
assert.equal(standardWpm('a b c d e f g h i jk', 60), 4);
assert.equal(standardWpm('', 0), 0);
""")
