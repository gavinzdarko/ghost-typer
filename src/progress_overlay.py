"""
Floating progress bar overlay for Ghost Typer.

A small borderless window that appears at the top-center of the screen
(below the menu bar) during typing. Shows a progress bar and countdown timer.

Uses AppKit/PyObjC (available on macOS system Python).
All methods MUST be called from the main thread (use _run_on_main in menu_bar_app).
"""

from __future__ import annotations

import AppKit
import objc


# Window dimensions
_WIDTH = 380
_HEIGHT = 28
_CORNER_RADIUS = 10
_BAR_HEIGHT = 6
_PADDING = 14
_BAR_Y = 11  # vertically centered


class ProgressOverlay:
    """Floating progress bar that appears during typing.

    The window is created once and reused — just hidden/shown via orderOut_/orderFront_.
    This avoids use-after-free crashes from PyObjC objects being in autorelease pools
    when Python drops its references.
    """

    def __init__(self) -> None:
        self._window: AppKit.NSWindow | None = None
        self._bar_view: _ProgressBarView | None = None
        self._label: AppKit.NSTextField | None = None
        self._pct: float = 0.0

    def _ensure_window(self) -> bool:
        """Create the overlay window if it doesn't exist yet. Returns True if ready."""
        if self._window is not None:
            return True

        screen = AppKit.NSScreen.mainScreen()
        if not screen:
            return False
        frame = screen.frame()
        top_y = frame.size.height - 24 - _HEIGHT - 8
        x = (frame.size.width - _WIDTH) / 2

        rect = AppKit.NSMakeRect(x, top_y, _WIDTH, _HEIGHT)
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False
        )
        window.setLevel_(AppKit.NSStatusWindowLevel + 1)
        window.setOpaque_(False)
        window.setBackgroundColor_(AppKit.NSColor.clearColor())
        window.setHasShadow_(True)
        window.setIgnoresMouseEvents_(True)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )
        # Prevent close() from releasing the window
        window.setReleasedWhenClosed_(False)

        content = _RoundedBackgroundView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _WIDTH, _HEIGHT)
        )
        window.setContentView_(content)

        bar_x = _PADDING
        bar_w = _WIDTH - _PADDING * 2 - 80
        self._bar_view = _ProgressBarView.alloc().initWithFrame_(
            AppKit.NSMakeRect(bar_x, _BAR_Y, bar_w, _BAR_HEIGHT)
        )
        content.addSubview_(self._bar_view)

        label_x = bar_x + bar_w + 10
        label_w = _WIDTH - label_x - _PADDING
        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(label_x, 4, label_w, 20)
        )
        label.setEditable_(False)
        label.setBordered_(False)
        label.setDrawsBackground_(False)
        label.setTextColor_(AppKit.NSColor.whiteColor())
        label.setFont_(AppKit.NSFont.monospacedSystemFontOfSize_weight_(12, AppKit.NSFontWeightMedium))
        label.setAlignment_(AppKit.NSTextAlignmentRight)
        label.setStringValue_("--")
        content.addSubview_(label)
        self._label = label

        self._window = window
        return True

    def show(self) -> None:
        """Show the overlay window. Must be called on main thread."""
        if self._ensure_window():
            self._bar_view.setProgress_(0.0)
            self._label.setStringValue_("--")
            self._window.orderFront_(None)

    def hide(self) -> None:
        """Hide the overlay (keeps window alive). Must be called on main thread."""
        if self._window:
            self._window.orderOut_(None)

    def destroy(self) -> None:
        """Final cleanup at app quit. After this, the overlay is unusable."""
        if self._window:
            self._window.orderOut_(None)
            self._window.close()
            self._window = None
            self._bar_view = None
            self._label = None

    def update(self, chars_typed: int, total_chars: int, wpm: int = 57) -> None:
        """Update progress and countdown. Must be called on main thread."""
        if not self._window or not self._bar_view or not self._label:
            return

        if total_chars <= 0:
            return

        pct = min(1.0, chars_typed / total_chars)
        self._bar_view.setProgress_(pct)

        # Calculate ETA
        remaining_chars = total_chars - chars_typed
        chars_per_sec = (wpm * 5) / 60 if wpm > 0 else 4.0
        eta_sec = max(0, int(remaining_chars / chars_per_sec))

        if eta_sec >= 60:
            minutes = eta_sec // 60
            seconds = eta_sec % 60
            self._label.setStringValue_(f"{minutes}m {seconds}s")
        else:
            self._label.setStringValue_(f"{eta_sec}s")

    @property
    def is_visible(self) -> bool:
        return self._window is not None and self._window.isVisible()


class _RoundedBackgroundView(AppKit.NSView):
    """Dark rounded-rect background view."""

    def drawRect_(self, rect):
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), _CORNER_RADIUS, _CORNER_RADIUS
        )
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.08, 0.08, 0.12, 0.92
        ).setFill()
        path.fill()


class _ProgressBarView(AppKit.NSView):
    """Custom progress bar: rounded track with filled portion."""

    _progress = 0.0

    def setProgress_(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bounds = self.bounds()
        radius = bounds.size.height / 2

        # Track (dark)
        track = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, radius, radius
        )
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.2, 0.2, 0.25, 1.0
        ).setFill()
        track.fill()

        # Fill
        if self._progress > 0.01:
            fill_w = max(bounds.size.height, bounds.size.width * self._progress)
            fill_rect = AppKit.NSMakeRect(0, 0, fill_w, bounds.size.height)
            fill_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                fill_rect, radius, radius
            )
            # Gradient from accent blue to green
            pct = self._progress
            r = 0.34 * (1 - pct) + 0.24 * pct
            g = 0.39 * (1 - pct) + 0.81 * pct
            b = 1.0 * (1 - pct) + 0.31 * pct
            AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                r, g, b, 1.0
            ).setFill()
            fill_path.fill()
