"""Pure replay of the planner's editable insertion region.

This models only our emitted text, never the destination document around it.
Unknown navigation invalidates the region rather than guessing a cursor target.
"""
# Limit relative cursor work even for very large documents.
MAX_CURSOR_ACTIONS = 4096

from .models import AbandonWord, ApplyFormatting, MakeMistake, PressKey, Rewrite, TypeText


class PlannedText:
    def __init__(self, text=""):
        self.text = text
        self.cursor = len(text)
        self.anchor = None
        self.valid = True

    def _insert(self, text):
        start, end = sorted((self.cursor, self.anchor if self.anchor is not None else self.cursor))
        self.text = self.text[:start] + text + self.text[end:]
        self.cursor = start + len(text)
        self.anchor = None

    def apply(self, actions):
        for action in actions:
            if isinstance(action, TypeText):
                self._insert(action.text)
            elif isinstance(action, MakeMistake):
                self._insert(action.correct_text)
            elif isinstance(action, AbandonWord):
                self._insert(action.replacement_text)
            elif isinstance(action, Rewrite):
                if action.delete_count > self.cursor:
                    self.valid = False
                    return self
                self.text = self.text[:self.cursor - action.delete_count] + self.text[self.cursor:]
                self.cursor -= action.delete_count
                self.apply(action.new_actions)
            elif isinstance(action, PressKey):
                if action.key in ("left", "right"):
                    self.cursor += -1 if action.key == "left" else 1
                    if not 0 <= self.cursor <= len(self.text):
                        self.valid = False
                        return self
                    self.anchor = None
                elif action.key == "backspace":
                    if self.anchor is not None:
                        self._insert("")
                    elif self.cursor:
                        self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
                        self.cursor -= 1
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
                    if self.cursor > len(self.text):
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
            or not text.isascii() or not replacement.isascii()
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
