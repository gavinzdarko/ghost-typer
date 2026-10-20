"""Pure replay of the planner's editable insertion region.

This models only our emitted text, never the destination document around it.
Unknown navigation invalidates the region rather than guessing a cursor target.
"""
# Limit relative cursor work even for very large documents.
MAX_CURSOR_ACTIONS = 4096

from .models import AbandonWord, ApplyFormatting, MakeMistake, PressKey, Rewrite, TypeText


class PlannedText:
    def __init__(self, text="", *, track_typos=False, max_typo_distance=None):
        self._text = text
        self._appends = []
        self._length = len(text)
        self.cursor = len(text)
        self.anchor = None
        self.valid = True
        self.typos = []
        self.track_typos = track_typos
        self.max_typo_distance = max_typo_distance

    @property
    def text(self):
        if self._appends:
            self._text = "".join([self._text, *self._appends])
            self._appends.clear()
        return self._text

    def __len__(self):
        return self._length

    def _insert(self, text):
        start, end = sorted((self.cursor, self.anchor if self.anchor is not None else self.cursor))
        self._replace(start, end, text)

    def _replace(self, start, end, text):
        delta = len(text) - (end - start)
        self.typos = [(wrong, correct, pos if pos + len(wrong) <= start else pos + delta)
                      for wrong, correct, pos in self.typos
                      if pos + len(wrong) <= start or pos >= end]
        if start == end == self._length:
            # Most replay events append to the insertion endpoint. Buffer them
            # instead of copying every earlier character for each keystroke.
            if text:
                self._appends.append(text)
        else:
            current = self.text
            self._text = current[:start] + text + current[end:]
        self._length += delta
        self.cursor = start + len(text)
        self.anchor = None
        if self.max_typo_distance is not None:
            self.typos = [entry for entry in self.typos if self._length - entry[2] <= self.max_typo_distance]

    def apply(self, actions):
        if not self.valid:
            return self
        for action in actions:
            if isinstance(action, TypeText):
                # Empty TypeText emits no event and cannot replace a selection.
                if action.text:
                    start = min(self.cursor, self.anchor if self.anchor is not None else self.cursor)
                    self._insert(action.text)
                    marker = action.proofread_typo
                    if self.track_typos and marker is not None:
                        wrong, correct, offset = marker
                        if action.text[offset:offset + len(wrong)] == wrong:
                            self.typos.append((wrong, correct, start + offset))
            elif isinstance(action, MakeMistake):
                self._insert(action.correct_text)
            elif isinstance(action, AbandonWord):
                self._insert(action.replacement_text)
            elif isinstance(action, Rewrite):
                if action.delete_count > self.cursor:
                    self.valid = False
                    return self
                self._replace(self.cursor - action.delete_count, self.cursor, "")
                self.apply(action.new_actions)
            elif isinstance(action, PressKey):
                if action.key in ("left", "right"):
                    self.cursor += -1 if action.key == "left" else 1
                    if not 0 <= self.cursor <= self._length:
                        self.valid = False
                        return self
                    self.anchor = None
                elif action.key == "backspace":
                    if self.anchor is not None:
                        self._insert("")
                    elif self.cursor:
                        self._replace(self.cursor - 1, self.cursor, "")
                    else:
                        self.valid = False
                        return self
                elif action.key in ("enter", "tab"):
                    self._insert("\n" if action.key == "enter" else "\t")
                else:
                    self.valid = False
                    return self
            elif isinstance(action, ApplyFormatting):
                if action.shortcut == ("shift", "right"):
                    if self.anchor is None:
                        self.anchor = self.cursor
                    self.cursor += 1
                    if self.cursor > self._length:
                        self.valid = False
                        return self
                else:
                    self.valid = False
                    return self
        return self


def replace_known_span(text, original, replacement, *, min_distance=0):
    """Select a unique ASCII span relative to the insertion cursor and return.

    Non-ASCII text can contain grapheme clusters with platform-dependent arrow
    movement. Leave such text untouched rather than navigating by code points.
    """
    if not isinstance(original, str) or not isinstance(replacement, str):
        return []
    pos = text.find(original)
    if (not original or not replacement or original == replacement
            or not text.isascii() or not replacement.isascii() or not replacement.isprintable()
            or any(not char.isprintable() and char != "\n" for char in text)
            or pos < 0 or text.find(original, pos + 1) >= 0):
        return []
    distance = len(text) - pos
    if distance < min_distance or 2 * distance > MAX_CURSOR_ACTIONS:
        return []
    tail = len(text) - pos - len(original)
    return ([PressKey(key="left") for _ in range(distance)]
            + [ApplyFormatting(shortcut=("shift", "right")) for _ in original]
            + [TypeText(text=replacement)]
            + [PressKey(key="right") for _ in range(tail)])
