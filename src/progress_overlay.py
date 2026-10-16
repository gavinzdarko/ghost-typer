"""
Floating progress bar overlay for Ghost Typer.

A small borderless window that appears at the top-center of the screen
(below the menu bar) during typing. Shows a progress bar and countdown timer.

Uses AppKit/PyObjC (available on macOS system Python).
All methods MUST be called from the main thread (use _run_on_main in menu_bar_app).
"""

from __future__ import annotations

import time

import AppKit


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
        self._locked_total_time: float = 0.0  # once set, countdown is based on this
        self._lock_pct: float = 0.0  # pct at which we locked
        self._lock_time: float = 0.0  # elapsed at which we locked
        self._last_eta_str: str = ""
        self._start_time: float = 0.0  # typing session start (time.time())
        self._tick_timer: AppKit.NSTimer | None = None
        self._planning_mode: bool = False
        self._planning_dots: int = 0
        self._paused_at: float | None = None
        self._paused_seconds: float = 0.0

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
        bar_w = _WIDTH - _PADDING * 2 - 110
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

    def show_planning(self) -> None:
        """Show the overlay in planning mode with animated dots. Main thread only."""
        if self._ensure_window():
            self._planning_mode = True
            self._paused_at = None
            self._paused_seconds = 0.0
            self._planning_dots = 0
            self._bar_view.setProgress_(-1.0)  # indeterminate
            self._label.setStringValue_("Planning")
            self._locked_total_time = 0.0
            self._lock_pct = 0.0
            self._lock_time = 0.0
            self._last_eta_str = ""
            self._start_time = 0.0
            self._window.orderFront_(None)
            self._start_tick_timer()

    def show(self) -> None:
        """Show a new session, or resume the existing paused session."""
        if self._ensure_window():
            self._planning_mode = False
            if self._paused_at is not None:
                self._paused_seconds += max(0.0, time.time() - self._paused_at)
                self._paused_at = None
                self._bar_view.setProgress_(self._pct)
                self._update_countdown()
            else:
                self._pct = 0.0
                self._bar_view.setProgress_(0.0)
                self._label.setStringValue_("--")
                self._locked_total_time = 0.0
                self._lock_pct = 0.0
                self._lock_time = 0.0
                self._last_eta_str = ""
                self._start_time = 0.0
                self._paused_seconds = 0.0
            self._window.orderFront_(None)
            self._start_tick_timer()

    def hide(self) -> None:
        """Hide the overlay after a session finishes or is cancelled."""
        self._paused_at = None
        self._stop_tick_timer()
        if self._window:
            self._window.orderOut_(None)

    def pause(self) -> None:
        """Hide while preserving progress and excluding the paused interval."""
        if self._paused_at is None:
            paused_at = time.time()
            self.hide()
            self._paused_at = paused_at

    def _active_elapsed(self) -> float:
        now = self._paused_at if self._paused_at is not None else time.time()
        return max(0.0, now - self._start_time - self._paused_seconds)

    def destroy(self) -> None:
        """Final cleanup at app quit. After this, the overlay is unusable."""
        self._stop_tick_timer()
        if self._window:
            self._window.orderOut_(None)
            self._window.close()
            self._window = None
            self._bar_view = None
            self._label = None

    def update(self, chars_typed: int, total_chars: int, start_time: float = 0.0, estimated_total: float = 0.0) -> None:
        """Update progress bar and ETA estimate. Called from progress callback."""
        if not self._window or not self._bar_view or not self._label:
            return

        if total_chars <= 0:
            return

        # Store start_time for the tick timer
        if start_time > 0 and self._start_time <= 0:
            self._start_time = start_time

        # Use upfront estimate if we don't have a better one yet
        if estimated_total > 0 and self._locked_total_time <= 0:
            self._locked_total_time = estimated_total

        pct = min(1.0, chars_typed / total_chars)
        self._pct = pct
        self._bar_view.setProgress_(pct)

        elapsed = self._active_elapsed() if self._start_time > 0 else 0

        # Refine estimate once we have real typing data
        if pct >= 0.05 and elapsed > 1:
            new_estimate = elapsed / pct
            # Smooth toward measured estimate (80% old, 20% new) for stability
            self._locked_total_time = self._locked_total_time * 0.8 + new_estimate * 0.2

        # Update the label
        self._update_countdown()

    def _update_planning_animation(self) -> None:
        """Animate 'Planning...' dots during AI planning phase."""
        if not self._label or not self._bar_view:
            return
        self._planning_dots = (self._planning_dots + 1) % 8
        dots = "." * ((self._planning_dots // 2) % 4)
        self._label.setStringValue_(f"Planning{dots}")
        # Sweep the indeterminate bar back and forth
        phase = self._planning_dots / 8.0
        self._bar_view.setIndeterminatePhase_(phase)

    def _update_countdown(self) -> None:
        """Recompute and display the countdown from current wall-clock time."""
        if not self._label or self._locked_total_time <= 0 or self._start_time <= 0:
            return

        elapsed = self._active_elapsed()
        remaining = max(0, self._locked_total_time - elapsed)
        remaining_sec = int(remaining)

        if remaining_sec >= 60:
            minutes = remaining_sec // 60
            seconds = remaining_sec % 60
            time_str = f"{minutes}m {seconds:02d}s"
        else:
            time_str = f"{remaining_sec}s"

        if time_str != self._last_eta_str:
            self._last_eta_str = time_str
            self._label.setStringValue_(time_str)

    def _start_tick_timer(self) -> None:
        """Start a 1-second NSTimer to tick the countdown independently."""
        self._stop_tick_timer()
        self._tick_timer = _TickHelper.alloc().init()
        self._tick_timer._overlay = self
        self._tick_timer.start()

    def _stop_tick_timer(self) -> None:
        """Stop the tick timer."""
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer = None

    @property
    def is_visible(self) -> bool:
        return self._window is not None and self._window.isVisible()


class _TickHelper(AppKit.NSObject):
    """NSObject subclass so NSTimer can call back via ObjC selector."""

    _overlay: ProgressOverlay | None = None
    _timer: AppKit.NSTimer | None = None

    def start(self) -> None:
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, b"tick:", None, True
        )

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def tick_(self, timer) -> None:
        if self._overlay is not None:
            if self._overlay._planning_mode:
                self._overlay._update_planning_animation()
            else:
                self._overlay._update_countdown()


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
    _indeterminate = False
    _phase = 0.0

    def setProgress_(self, value: float) -> None:
        if value < 0:
            # Indeterminate mode
            self._indeterminate = True
            self._phase = 0.0
        else:
            self._indeterminate = False
            self._progress = max(0.0, min(1.0, value))
        self.setNeedsDisplay_(True)

    def setIndeterminatePhase_(self, phase: float) -> None:
        self._phase = phase
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        import math
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

        if self._indeterminate:
            # Pulsing shimmer effect
            pulse_w = bounds.size.width * 0.35
            center_x = self._phase * (bounds.size.width + pulse_w) - pulse_w * 0.5
            fill_x = max(0, center_x - pulse_w / 2)
            fill_end = min(bounds.size.width, center_x + pulse_w / 2)
            fill_w = fill_end - fill_x
            if fill_w > 1:
                fill_rect = AppKit.NSMakeRect(fill_x, 0, fill_w, bounds.size.height)
                fill_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    fill_rect, radius, radius
                )
                # Purple accent for planning
                alpha = 0.5 + 0.5 * math.sin(self._phase * math.pi)
                AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.55, 0.36, 1.0, alpha
                ).setFill()
                fill_path.fill()
        elif self._progress > 0.01:
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
