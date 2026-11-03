from test_core_browser_capture import pytestmark, run


def test_live_exports_preserve_pending_bursts_and_final_measurements():
    run('freeform.html', """
function typeAt(index) { key('typing-area', 'a', 100 + index * 100); }
typeAt(0);
typeAt(1);
typeAt(2);
// Exporting a run that is not yet long enough must not discard its intervals.
assert.equal(buildJSON().bursts.count, 0);
typeAt(3);
const partial = buildJSON();
assert.deepEqual(partial.bursts, { count: 1, avg_len: 3, avg_iki: 100 });
assert.deepEqual(buildJSON(), partial);
assert.deepEqual(bursts, []);
assert.deepEqual(currentBurst, [100, 100, 100]);
typeAt(4);
typeAt(5);
typeAt(6);
showResults();
const finishedData = buildJSON();
assert.deepEqual(finishedData.bursts, { count: 1, avg_len: 6, avg_iki: 100 });
assert.deepEqual(bursts, [{len: 6, avg: 100}]);
showResults();
assert.deepEqual(buildJSON(), finishedData);
reset();
for (let i = 0; i < 7; i++) typeAt(i);
showResults();
assert.deepEqual(buildJSON(), finishedData);
""")


def test_live_export_includes_finalized_and_pending_bursts_once():
    run('freeform.html', """
for (let i = 0; i < 4; i++) key('typing-area', 'a', 100 + i * 100);
key('typing-area', 'b', 1000);
for (let i = 1; i <= 4; i++) key('typing-area', 'c', 1000 + i * 100);
const data = buildJSON();
assert.deepEqual(data.bursts, { count: 2, avg_len: 4, avg_iki: 100 });
assert.deepEqual(buildJSON(), data);
assert.equal(bursts.length, 1);
assert.equal(currentBurst.length, 4);
showResults();
assert.deepEqual(buildJSON(), data);
""")
