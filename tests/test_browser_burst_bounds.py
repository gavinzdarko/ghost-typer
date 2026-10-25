from test_core_browser_capture import pytestmark, run


def test_long_fast_burst_exports_ordered_bounds_and_keeps_raw_measurement():
    run('index.html', """
started = true;
startTime = 100;
now = 1100;
bursts.push({length: 50, avgIki: 80});
const data = buildConfigJSON();
assert.equal(data.ghost_typer_settings.burst_length_min, 30);
assert.equal(data.ghost_typer_settings.burst_length_max, 30);
assert.equal(data.measured_data.bursts.avg_length, 50);
""")
