from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_css_preformatted_modes_keep_spaces_tabs_and_lines():
    for mode in ("pre", "pre-wrap", "break-spaces"):
        assert text(f'<div style="white-space:{mode}">a  b\n c\td</div>') == "a  b\n c\td"


def test_css_whitespace_is_inherited_and_normal_can_restore_collapsing():
    assert text('<div style="white-space:pre-wrap">a<span>  b\nc</span>d</div>') == "a  b\ncd"
    assert text('<div style="white-space:pre-wrap">a<span style="white-space:normal">  b\nc</span>d</div>') == "a b cd"


def test_css_whitespace_respects_inline_cascade_and_importance():
    assert text('<div style="white-space:pre-wrap!important;white-space:normal">a  b</div>') == "a  b"
    assert text('<div style="white-space:pre;white-space:normal">a  b</div>') == "a b"


def test_inline_preformatted_spans_are_one_planner_paragraph():
    from src.models import Settings, Pause
    from src.typing_planner import TypingPlanner
    html = '<div style="white-space:pre-wrap">' + '<span>word </span>' * 30 + '</div>'
    segments = TextParser().parse(html, is_html=True)
    assert len(segments) == 1
    assert segments[0].text == 'word ' * 30
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0,
        proofread_probability=0, revisit_probability=0), ai_enabled=False)
    plan = planner.plan(segments)
    assert sum(isinstance(action, Pause) for action in plan.actions) == 1


def test_mixed_css_modes_keep_one_paragraph_and_their_own_spacing():
    html = '  before <span style="white-space:pre"> a  b </span>  after  '
    segments = TextParser().parse(html, is_html=True)
    assert len(segments) == 1
    assert segments[0].text == 'before  a  b  after'


def test_pre_line_overrides_inherited_space_preservation_but_keeps_newlines():
    assert text('<div style="white-space:pre-wrap">a<span style="white-space:pre-line">  b</span>d</div>') == 'a bd'
    assert text('<div style="white-space:pre-line">  a  \n  b\t c  </div>') == 'a\nb c'
    assert text('<div style="white-space:pre-line"><span>a </span><span> b</span></div>') == 'a b'
