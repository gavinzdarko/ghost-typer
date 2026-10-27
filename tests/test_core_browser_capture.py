"""Exercise browser capture logic in Node without browser or keyboard access."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is needed for browser capture regressions")
ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const assert = require('node:assert/strict');
let now = 100;
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', style: {}, innerHTML: '', textContent: '', readOnly: false,
    classList: {
      values: new Set(),
      add(value) { this.values.add(value); },
      remove(value) { this.values.delete(value); },
      contains(value) { return this.values.has(value); },
      toggle() {},
    },
    listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; },
    focus() {}, scrollIntoView() {}, getContext() {return new Proxy({}, {get: () => () => {}});},
  });
  return elements.get(id);
}
const document = {getElementById: element, addEventListener() {}};
const performance = {now: () => now};
const window = {scrollTo() {}};
const navigator = {clipboard: {writeText: async () => {}}};
function setInterval() { return 1; }
function clearInterval() {}
function setTimeout() {}
function key(id, value, time, options = {}) {
  now = time;
  element(id).listeners.keydown({key: value, preventDefault() {}, ...options});
}
"""


def run(page, assertions):
    source = (ROOT / "typing-test" / page).read_text()
    script = re.search(r"<script>(.*?)</script>", source, re.DOTALL).group(1)
    result = subprocess.run([NODE, "-e", HARNESS + script + assertions],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("page,input_id,counter,intervals", [
    ("index.html", "typing-input", "totalKeystrokes", "ikiValues"),
    ("freeform.html", "typing-area", "charCount", "ikis"),
])
def test_only_text_keys_affect_session_start_and_interkey_timing(page, input_id, counter, intervals):
    run(page, f"""
key('{input_id}', 'Shift', 100);
key('{input_id}', 'v', 110, {{metaKey: true}});
key('{input_id}', 'a', 120, {{ctrlKey: true}});
key('{input_id}', 'Process', 130, {{isComposing: true}});
assert.equal(started, false);
key('{input_id}', 'a', 200);
key('{input_id}', 'Shift', 250);
key('{input_id}', 'ArrowLeft', 260);
key('{input_id}', 'B', 300);
assert.equal({counter}, 2);
assert.deepEqual({intervals}, [100]);
key('{input_id}', 'Backspace', 400);
key('{input_id}', 'c', 500);
assert.deepEqual({intervals}, [100]);
""")


def test_finished_freeform_results_and_json_remain_a_single_snapshot():
    run("freeform.html", r"""
key('typing-area', 'a', 100);
key('typing-area', 'b', 200);
key('typing-area', 'Enter', 300);
assert.equal(charCount, 3);
element('typing-area').value = 'ab\n';
now = 1100;
showResults();
const snapshot = buildJSON();
assert.equal(snapshot.time_s, 1);
assert.equal(element('typing-area').readOnly, true);
now = 10000;
key('typing-area', 'x', 11000);
showResults();
assert.deepEqual(buildJSON(), snapshot);
reset();
assert.equal(element('typing-area').readOnly, false);
assert.equal(element('s-chars').textContent, 0);
key('typing-area', 'z', 12000);
assert.equal(charCount, 1);
""")


def test_finished_prompt_export_does_not_decay_while_reading_results():
    run("index.html", """
key('typing-input', 'a', 100);
key('typing-input', 'b', 200);
now = 1100;
showSummary = () => {};
finish();
const snapshot = buildConfigJSON();
now = 10000;
finish();
assert.deepEqual(buildConfigJSON(), snapshot);
startNewRound();
assert.equal(started, false);
assert.equal(finishTime, null);
""")


def test_prompt_summary_charts_measure_visible_layout_on_each_round():
    run("index.html", """
const summary = element('summary');
for (const id of ['iki-chart', 'fatigue-chart']) {
  // A display:none ancestor gives descendants zero layout width. Model that
  // browser contract so drawing before revealing the summary cannot pass.
  Object.defineProperty(element(id), 'offsetWidth', {
    get() { return summary.classList.contains('visible') ? 400 : 0; },
  });
}
for (let round = 0; round < 2; round++) {
  startNewRound();
  assert.equal(summary.classList.contains('visible'), false);
  key('typing-input', 'a', 100);
  key('typing-input', 'b', 200);
  wpmOverTime.push({time: 5, wpm: 60, errorRate: 0},
                   {time: 10, wpm: 62, errorRate: 0});
  now = 11100;
  finish();
  assert.equal(summary.classList.contains('visible'), true);
  assert.equal(element('iki-chart').width, 800);
  assert.equal(element('fatigue-chart').width, 800);
}
""")
