import pytest

from test_core_browser_capture import run


@pytest.mark.parametrize('page,input_id,intervals,live_fn,live_id', [
    ('index.html', 'typing-input', 'ikiValues', 'updateLiveStats', 'live-iki'),
    ('freeform.html', 'typing-area', 'ikis', 'updateLive', 's-iki'),
])
def test_live_mean_uses_bounded_work_and_resets(page, input_id, intervals, live_fn, live_id):
    run(page, f"""
let sampleVisits = 0;
{intervals}.reduce = function(callback, initial) {{
  return Array.prototype.reduce.call(this, (...args) => {{ sampleVisits++; return callback(...args); }}, initial);
}};
for (let index = 0; index < 300; index++) key('{input_id}', 'a', 100 + index * 100);
assert.equal(element('{live_id}').textContent, 100);
for (let index = 0; index < 10; index++) {live_fn}();
assert.ok(sampleVisits <= 600, `Live mean read ${{sampleVisits}} samples`);
key('{input_id}', 'Backspace', 31000);
key('{input_id}', 'b', 32000);
assert.equal(element('{live_id}').textContent, 100);
{'startNewRound' if page == 'index.html' else 'reset'}();
assert.equal(element('{live_id}').textContent, 0);
key('{input_id}', 'a', 40000);
key('{input_id}', 'b', 40250);
assert.equal(element('{live_id}').textContent, 250);
""")


def test_freeform_live_backspace_mean_and_reset_do_not_scan_samples():
    run('freeform.html', """
let visits = 0;
bsIkis.reduce = function(callback, initial) {
  return Array.prototype.reduce.call(this, (...args) => { visits++; return callback(...args); }, initial);
};
key('typing-area', 'a', 100);
key('typing-area', 'Backspace', 200);
key('typing-area', 'Backspace', 300);
key('typing-area', 'Backspace', 500);
assert.equal(element('s-bsrate').textContent, 150);
for (let index = 0; index < 100; index++) updateLive();
assert.equal(visits, 0);
reset();
assert.equal(element('s-bsrate').textContent, 0);
key('typing-area', 'Backspace', 1000);
key('typing-area', 'Backspace', 1250);
assert.equal(element('s-bsrate').textContent, 250);
""")
