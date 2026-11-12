"""Browser calibration suggestions must survive the application's settings loader."""
import json
import re
import subprocess

from bs4 import BeautifulSoup
import pytest

from src.models import Settings
from test_core_browser_capture import HARNESS, NODE, ROOT, pytestmark


def capture(page, script):
    source = (ROOT / 'typing-test' / page).read_text()
    product = re.search(r'<script>(.*?)</script>', source, re.DOTALL).group(1)
    result = subprocess.run([NODE, '-e', HARNESS + product + script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def assert_settings_survive_import(settings):
    loaded = Settings.from_dict(settings).to_dict()
    assert {key: loaded[key] for key in settings} == settings


@pytest.mark.parametrize('gap_ms', [40000, 100, 1])
def test_prompt_exports_supported_speed_without_changing_measurements(gap_ms):
    data = capture('index.html', f"""
PROMPTS.splice(0, PROMPTS.length, 'abcdefghijklmnopqrst');
init();
showSummary = () => {{}};
promptChars.forEach((char, index) => key('typing-input', char, 100 + index * {gap_ms}));
assert.equal(finished, true);
console.log(JSON.stringify(buildConfigJSON()));
""")
    settings = data['ghost_typer_settings']
    assert_settings_survive_import(settings)
    measured = round(20 / 5 / (19 * gap_ms / 1000) * 60)
    assert data['measured_data']['wpm'] == measured
    assert settings['wpm'] == max(1, min(1000, measured))
    assert settings['wpm_variance'] == min(1000, round(measured * .2))


def test_unstarted_prompt_snapshot_has_finite_speed_fields():
    data = capture('index.html', 'console.log(JSON.stringify(buildConfigJSON()));')
    assert data['measured_data']['wpm'] == 0
    assert data['ghost_typer_settings']['wpm'] == 1
    assert_settings_survive_import(data['ghost_typer_settings'])


@pytest.mark.parametrize('count,gap_ms', [(20, 40000), (20, 100), (20, 1),
                                         (2, 7200000), (4002, 1)])
def test_freeform_suggestions_survive_import_and_preserve_raw_data(count, gap_ms):
    data = capture('freeform.html', f"""
for (let index = 0; index < {count}; index++) key('typing-area', 'a', 100 + index * {gap_ms});
area.value = 'a'.repeat({count});
showResults();
console.log(JSON.stringify({{html: element('t-config').innerHTML, raw: buildJSON()}}));
""")
    rows = BeautifulSoup(data['html'], 'html.parser').find_all('tr')
    suggestions = {}
    for row in rows:
        key, value = [cell.get_text() for cell in row.find_all('td')]
        if key in Settings().to_dict():
            suggestions[key] = float(value[:-1]) if value.endswith('s') else json.loads(value)
    assert len(suggestions) == 7
    assert_settings_survive_import(suggestions)
    measured = round(count / 5 / ((count - 1) * gap_ms / 1000) * 60)
    assert data['raw']['wpm'] == measured
    assert suggestions['wpm'] == max(1, min(1000, measured))
    assert suggestions['wpm_variance'] == min(1000, round(measured * .2))
    if gap_ms > 500:
        assert data['raw']['pauses']['avg_ms'] == gap_ms
    if count == 4002:
        assert data['raw']['bursts']['avg_len'] == count - 1
