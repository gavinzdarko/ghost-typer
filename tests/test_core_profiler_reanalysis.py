from typing_profiler import KeyEvent, TypingAnalyzer


def events():
    return [KeyEvent(i * .2, char, is_space=char == " ",
                     is_backspace=char == "<BS>")
            for i, char in enumerate(list("some words here ") + ["<BS>"] + list("other words "))]


def test_reanalysis_does_not_double_corrections_or_pause_statistics():
    analyzer = TypingAnalyzer(events())
    first = analyzer.analyze()
    assert analyzer.analyze() == first
    assert len(analyzer.corrections) == 1


def test_reanalysis_after_new_events_matches_a_fresh_analyzer():
    analyzer = TypingAnalyzer(events())
    analyzer.analyze()
    analyzer.events.extend(KeyEvent(8 + i * .2, c) for i, c in enumerate("added words "))
    assert analyzer.analyze() == TypingAnalyzer(analyzer.events).analyze()
