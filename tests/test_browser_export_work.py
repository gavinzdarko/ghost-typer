from test_core_browser_capture import pytestmark, run


def test_prompt_export_computes_interval_statistics_with_linear_reduction_work():
    run("index.html", """
started = true;
startTime = 100;
now = 1100;
ikiValues.push(...Array.from({length: 10000}, (_, i) => 100 + i % 3));
let visits = 0;
const reduce = ikiValues.reduce;
ikiValues.reduce = function(callback, initial) {
  return reduce.call(this, (...args) => { visits++; return callback(...args); }, initial);
};
const data = buildConfigJSON();
assert.equal(data.measured_data.iki.mean_ms, 101);
assert.equal(data.measured_data.iki.std_dev_ms, 1);
assert.ok(visits <= 3 * ikiValues.length, `Reduction visited ${visits} intervals`);
""")
