from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from src.progress_overlay import ProgressOverlay, _WIDTH, _HEIGHT


@pytest.mark.parametrize('origin', [(1920, 300), (-1600, -200), (0, 0)])
def test_overlay_is_positioned_inside_selected_displays_visible_frame(origin):
    x, y = origin
    frame = SimpleNamespace(origin=SimpleNamespace(x=x, y=y),
                            size=SimpleNamespace(width=1600, height=900))
    with patch('src.progress_overlay.AppKit') as kit, \
         patch('src.progress_overlay._RoundedBackgroundView'), \
         patch('src.progress_overlay._ProgressBarView'):
        kit.NSScreen.mainScreen.return_value.visibleFrame.return_value = frame
        kit.NSStatusWindowLevel = 1
        kit.NSWindowCollectionBehaviorCanJoinAllSpaces = 1
        kit.NSWindowCollectionBehaviorStationary = 2
        assert ProgressOverlay()._ensure_window()
        placement = kit.NSMakeRect.call_args_list[0].args
    assert placement == (x + (1600 - _WIDTH) / 2, y + 900 - _HEIGHT - 8, _WIDTH, _HEIGHT)
    assert x <= placement[0] < x + 1600
    assert y <= placement[1] < y + 900
