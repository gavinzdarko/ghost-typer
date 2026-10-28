"""
Parses HTML/rich text clipboard content into TextSegment objects with formatting metadata.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

from .models import TextSegment

logger = logging.getLogger(__name__)


class TextParser:
    """Parses HTML or plain text into a list of TextSegment objects."""

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    BLOCK_TAGS = {"p", "div", "blockquote", "section", "article", "header", "footer",
                  "main", "aside", "address", "nav", "figure", "figcaption",
                  "form", "search", "fieldset", "legend", "dialog", "hgroup"}
    LIST_ITEM_TAG = "li"
    ORDERED_LIST_TAG = "ol"
    UNORDERED_LIST_TAG = "ul"

    def parse(self, content: str, is_html: bool = False) -> list[TextSegment]:
        """Parse content into TextSegments.

        Args:
            content: The text or HTML content to parse.
            is_html: Whether the content is HTML.

        Returns:
            A list of TextSegment objects with formatting metadata.
        """
        if not content:
            return []

        if is_html:
            try:
                return self._parse_html(content)
            except Exception as exc:
                # Rich clipboard input must never become literal HTML keystrokes
                # when parsing fails (for example on an excessively nested DOM).
                logger.exception("HTML parsing failed; refusing to type raw markup")
                raise ValueError(
                    "Could not parse rich clipboard text safely. Copy as plain text and retry."
                ) from exc

        return self._parse_plain_text(content)

    def _parse_plain_text(self, text: str) -> list[TextSegment]:
        """Parse plain text preserving paragraph structure."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        segments: list[TextSegment] = []
        for part in re.split(r"(\n+)", text):
            if not part:
                continue
            fmt = {}
            if part.startswith("\n"):
                fmt = {"paragraph_break" if len(part) > 1 else "linebreak": True}
            segments.append(TextSegment(text=part, formatting=fmt))

        return segments

    # Tags whose content should be removed entirely
    STRIP_TAGS = {"script", "style", "noscript", "svg", "math", "head", "title", "meta", "link", "base", "template"}

    # Regex for citation-like <sup> content: [1], [a], [1][2], [edit], etc.
    _SUP_CITATION_RE = re.compile(r"^\s*\[[\d\w,\s]+\]\s*$")

    def _parse_html(self, html: str) -> list[TextSegment]:
        """Parse HTML content into plain-text TextSegments.

        Strips all formatting (bold, italic, links, colors) so the typed text
        inherits the destination's style. Also removes citation markers like [1][2].
        """
        soup = BeautifulSoup(html, "html.parser")

        # Closed disclosure widgets render only their first direct summary.
        # Select it before hidden elements are removed: a hidden first summary
        # must not promote a later summary into the visible disclosure label.
        for details in soup.find_all("details"):
            if not details.has_attr("open"):
                summary = details.find("summary", recursive=False)
                for child in list(details.children):
                    if child is not summary:
                        child.extract()

        # Remove hidden subtrees before walking their descendants.
        # Decomposition also clears descendants'
        # attributes, so skip those entries in the original traversal snapshot.
        for tag in soup.find_all(True):
            if tag.attrs is not None and self._is_hidden(tag):
                tag.decompose()
            elif tag.attrs is not None:
                mode = self._inline_keyword(tag.get("style", ""), "content-visibility",
                                            {"visible", "hidden", "auto"})
                if mode == "hidden" and self._content_visibility_applies(tag):
                    # The container still creates its own block boundary.
                    tag.clear()

        # Strip tags that should always be removed
        for tag in soup.find_all(self.STRIP_TAGS):
            # Removing a head also removes its descendants; skip detached
            # metadata instead of trying to replace it a second time.
            if tag.parent is None:
                continue
            tag.replace_with("")

        # Strip citation <sup> tags specifically (preserve legitimate superscripts like x²)
        for sup in soup.find_all("sup"):
            classes = sup.get("class", [])
            text_content = sup.get_text()
            if ("reference" in classes or "noprint" in classes
                    or self._SUP_CITATION_RE.match(text_content)):
                sup.replace_with("")

        self._strip_invisible_text(soup)
        body = soup.body if soup.body else soup
        segments: list[TextSegment] = []
        self._walk_node(body, {}, segments, list_context=None, list_counter=None)

        # Strip all formatting from segments — we only want plain text
        for seg in segments:
            seg.formatting = {k: v for k, v in seg.formatting.items()
                              if k in ("paragraph_break", "linebreak", "list_type",
                                       "list_index", "list_prefix", "heading_level", "preformatted",
                                       "explicit_break_count", "_white_space")}

        return self._clean_segments(segments)

    @staticmethod
    def _strip_invisible_text(root: Tag) -> None:
        """Remove invisible text while allowing descendants to restore visibility.

        Unlike display:none, visibility:hidden is inherited and a child can
        override it. Clean before the text walk reads descendants.
        """
        stack = [(root, False)]
        while stack:
            node, inherited_hidden = stack.pop()
            if isinstance(node, NavigableString):
                if inherited_hidden:
                    node.extract()
                continue
            if not isinstance(node, Tag):
                continue
            hidden = inherited_hidden
            value = TextParser._inline_keyword(node.get("style", ""), "visibility",
                                              {"visible", "hidden", "collapse"})
            if value in ("hidden", "collapse"):
                hidden = True
            elif value in ("visible", "initial"):
                hidden = False
            # Keep visibility for parser-generated markers as well as literal
            # text. A visible descendant does not restore its parent's marker.
            node._ghost_visibility_hidden = hidden
            stack.extend((child, hidden) for child in node.children)

    @staticmethod
    def _inline_values(style: str, prop: str):
        """Read declarations without treating comments/strings as CSS rules.

        Comments separate tokens rather than joining identifiers. Quoted and
        grouped values retain their delimiters, so a literal-looking rule
        inside content, a URL or a custom property cannot change visibility.
        """
        parts = []
        quote = None
        closing = []
        pairs = {"(": ")", "[": "]", "{": "}"}
        index = 0
        while index < len(style):
            char = style[index]
            if char == "\\":
                parts.append(style[index:index + 2])
                index += 2
                continue
            if quote is not None:
                parts.append(char)
                if char == quote or char in "\n\r\f":
                    quote = None
            elif char in ("'", '"'):
                quote = char
                parts.append(char)
            elif style.startswith("/*", index):
                end = style.find("*/", index + 2)
                parts.append(" ")
                index = len(style) if end < 0 else end + 2
                continue
            elif char in pairs:
                closing.append(pairs[char])
                parts.append(char)
            elif closing and char == closing[-1]:
                closing.pop()
                parts.append(char)
            elif char == ";" and not closing:
                declaration = "".join(parts).partition(":")
                if declaration[0].strip().lower() == prop:
                    yield declaration[2]
                parts.clear()
            else:
                parts.append(char)
            index += 1
        declaration = "".join(parts).partition(":")
        if declaration[0].strip().lower() == prop:
            yield declaration[2]

    @staticmethod
    def _inline_keyword(style: str, prop: str, keywords: set[str]) -> Optional[str]:
        """Choose literal values after validation, before priority/order.

        Variables, escaped identifiers and external CSS remain outside this
        parser's model. Recognize modern whitespace shorthand syntax too so a
        valid unsupported mode does not incorrectly revive an earlier rule.
        """
        globals_ = {"inherit", "initial", "unset", "revert", "revert-layer"}
        candidates = []
        for raw in TextParser._inline_values(style, prop):
            important = bool(re.search(r"!\s*important\s*$", raw, re.IGNORECASE))
            value = " ".join(re.sub(r"!\s*important\s*$", "", raw, flags=re.IGNORECASE).lower().split())
            valid = value in keywords | globals_
            if not valid and prop == "white-space":
                words = value.split()
                tokens = set(words)
                collapse = {"collapse", "discard", "preserve", "preserve-breaks", "preserve-spaces", "break-spaces"}
                wrap = {"wrap", "nowrap"}
                trim = {"none", "discard-before", "discard-after", "discard-inner"}
                valid = (bool(words) and len(words) == len(tokens)
                         and tokens <= collapse | wrap | trim
                         and len(tokens & collapse) <= 1 and len(tokens & wrap) <= 1
                         and not ("none" in tokens and len(tokens & trim) > 1))
            if valid:
                candidates.append((important, value))
        if not candidates:
            return None
        return max(enumerate(candidates), key=lambda item: (item[1][0], item[0]))[1][1]

    @staticmethod
    def _content_visibility_applies(node: Tag) -> bool:
        """Recognize containment-capable boxes from HTML defaults/inline CSS.

        Ordinary inline text and display:contents cannot skip their contents.
        Unknown display modes stay visible rather than silently dropping text.
        """
        display = TextParser._inline_display(node)
        if display is not None:
            if display == "inherit":
                return isinstance(node.parent, Tag) and TextParser._content_visibility_applies(node.parent)
            if display not in ("revert", "revert-layer"):
                # Multi-keyword display accepts either token order. Normalize
                # the outer/inner roles before testing containment capability.
                tokens = set(display.split())
                if len(tokens) > 1:
                    outer = next((role for role in ("inline", "block", "run-in") if role in tokens), "block")
                    inner = next((role for role in ("flow-root", "flow", "flex", "grid", "table", "ruby")
                                  if role in tokens), "flow")
                    display = f"{outer} {inner}"
                return display in {"block", "flow-root", "list-item", "flex", "grid",
                                   "inline-block", "inline-flex", "inline-grid", "table-caption",
                                   "flow", "block flow", "block flow-root", "block flex", "block grid",
                                   "inline flow-root", "inline flex", "inline grid"}
        return node.name in (TextParser.BLOCK_TAGS | TextParser.HEADING_TAGS | {
            "body", "main", "aside", "address", "nav", "figure", "figcaption",
            "pre", "details", "summary", "ul", "ol", "li", "menu", "dl", "dt", "dd",
            "form", "fieldset", "legend", "dialog", "caption", "hr",
        })

    @staticmethod
    def _inline_display(node: Tag) -> Optional[str]:
        """Select a valid literal display declaration using inline precedence.

        External stylesheets, variables and browser layout are outside this
        parser's model. Invalid literals must not reveal default-hidden text.
        """
        declarations = TextParser._inline_values(node.get("style", ""), "display")
        outer = {"block", "inline", "run-in"}
        inner = {"flow", "flow-root", "table", "flex", "grid", "ruby"}
        singles = outer | inner | {
            "list-item", "none", "contents", "inline-block", "inline-table", "inline-flex", "inline-grid",
            "table-row-group", "table-header-group", "table-footer-group", "table-row", "table-cell",
            "table-column-group", "table-column", "table-caption", "ruby-base", "ruby-text",
            "ruby-base-container", "ruby-text-container", "inherit", "initial", "unset", "revert", "revert-layer",
        }
        valid = []
        for raw in declarations:
            important = bool(re.search(r"!\s*important\s*$", raw, re.IGNORECASE))
            value = " ".join(re.sub(r"!\s*important\s*$", "", raw, flags=re.IGNORECASE).lower().split())
            words = value.split()
            tokens = set(words)
            if value in singles:
                allowed = True
            elif "list-item" in tokens:
                allowed = (len(tokens) == len(words) and tokens <= outer | {"flow", "flow-root", "list-item"}
                           and len(tokens & outer) <= 1 and len(tokens & {"flow", "flow-root"}) <= 1)
            else:
                allowed = (len(words) == 2 and len(tokens & outer) == 1 and len(tokens & inner) == 1)
            if allowed:
                valid.append((important, value))
        if not valid:
            return None
        return max(enumerate(valid), key=lambda item: (item[1][0], item[0]))[1][1]

    @staticmethod
    def _is_hidden(node: Tag) -> bool:
        if node.has_attr("hidden"):
            return True
        closed_dialog = node.name == "dialog" and not node.has_attr("open")
        display = TextParser._inline_display(node)
        if display is None:
            return closed_dialog
        if display in ("revert", "revert-layer"):
            return closed_dialog
        return display == "none"

    @staticmethod
    def _has_list_marker(node: Tag) -> bool:
        """Only list-item boxes generate a marker, including inherited display."""
        display = TextParser._inline_display(node)
        if display == "inherit" and isinstance(node.parent, Tag):
            return TextParser._has_list_marker(node.parent)
        if display is None or display in ("revert", "revert-layer"):
            return node.name == TextParser.LIST_ITEM_TAG
        return "list-item" in display.split()

    @staticmethod
    def _has_inline_outer_display(node: Tag) -> bool:
        """Honor inline display overrides on otherwise block containers.

        This only determines generated outer separators; descendants retain
        their own layout and whitespace behavior.
        """
        default_inline = node.name not in (TextParser.BLOCK_TAGS | TextParser.HEADING_TAGS | {
            "html", "body", "pre", "details", "summary", "ul", "ol", "li",
            "menu", "dl", "dt", "dd", "table", "tr", "td", "th", "caption",
            "form", "fieldset", "legend", "dialog", "search", "hgroup",
        })
        display = TextParser._inline_display(node)
        if display is None:
            return default_inline
        if display == "inherit" and isinstance(node.parent, Tag):
            return TextParser._has_inline_outer_display(node.parent)
        if display in ("revert", "revert-layer"):
            return default_inline
        return "inline" in display.split() or display in {"inline", "inline-block", "inline-flex", "inline-grid",
                           "inline-table", "contents", "initial", "unset", "inline flow",
                           "inline flow-root", "inline flex", "inline grid", "inline table", "ruby",
                           "ruby-base", "ruby-text", "ruby-base-container", "ruby-text-container"}

    def _walk_node(
        self,
        node: Tag | NavigableString,
        inherited_fmt: dict,
        segments: list[TextSegment],
        list_context: Optional[str],
        list_counter: Optional[list[int | str]],
    ) -> None:
        """Recursively walk the DOM tree building TextSegments."""
        if isinstance(node, (Comment, Declaration, Doctype, ProcessingInstruction)):
            return
        if isinstance(node, NavigableString):
            text = str(node)
            # Collapse whitespace first (handles "\n  " from prettified HTML)
            # HTML collapses ASCII layout whitespace, while nonbreaking,
            # thin, and em spaces remain visible source characters.
            collapsed = (text.replace("\r\n", "\n").replace("\r", "\n")
                         if inherited_fmt.get("preformatted")
                         else re.sub(r"[ \t\r\n\f]+", " ", text))
            if collapsed:
                segments.append(TextSegment(text=collapsed, formatting=dict(inherited_fmt)))
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower() if node.name else ""
        fmt = dict(inherited_fmt)
        if tag == "pre":
            # PRE's own default overrides a parent's inherited pre-line mode.
            # Its explicit inline white-space declaration is considered below.
            fmt["preformatted"] = True
            fmt["_white_space"] = "pre"
        visibility_hidden = bool(getattr(node, "_ghost_visibility_hidden", False))

        # Compute formatting from tag
        if tag in ("b", "strong"):
            fmt["bold"] = True
        elif tag in ("i", "em"):
            fmt["italic"] = True
        elif tag in ("u", "ins"):
            fmt["underline"] = True
        elif tag in ("s", "strike", "del"):
            fmt["strikethrough"] = True
        elif tag in ("code", "kbd", "samp"):
            fmt["code"] = True
        elif tag == "a":
            href = node.get("href")
            if href:
                fmt["link"] = str(href)

        # Inline style extraction
        style = node.get("style", "")
        if style:
            self._apply_inline_styles(style, fmt)

        # Rich clipboard producers often use CSS rather than PRE elements.
        # white-space is inherited, with normal/nowrap restoring collapse.
        mode = self._inline_keyword(style, "white-space",
                                    {"normal", "nowrap", "pre", "pre-wrap", "pre-line", "break-spaces"})
        if mode is not None:
            # Wrapping changes layout, while the collapse component determines
            # which source characters we type. Normalize equivalent modern
            # shorthands, including omitted components' initial values.
            tokens = set(mode.split())
            if tokens <= {"collapse", "preserve", "preserve-breaks", "break-spaces",
                          "wrap", "nowrap", "none"}:
                if tokens & {"preserve", "break-spaces"}:
                    mode = "pre"
                elif "preserve-breaks" in tokens:
                    mode = "pre-line"
                else:
                    mode = "normal"
        if mode is not None:
            if mode in ("pre", "pre-wrap", "break-spaces"):
                fmt["preformatted"] = True
                fmt["_white_space"] = "pre"
            elif mode == "pre-line":
                fmt["preformatted"] = True
                fmt["_white_space"] = "pre-line"
            elif mode in ("inherit", "unset"):
                # Explicit inheritance overrides PRE's element default too.
                for key in ("preformatted", "_white_space"):
                    if key in inherited_fmt:
                        fmt[key] = inherited_fmt[key]
                    else:
                        fmt.pop(key, None)
            elif mode in ("normal", "nowrap", "initial"):
                fmt.pop("preformatted", None)
                fmt.pop("_white_space", None)

        # Headings
        inline_container = self._has_inline_outer_display(node)
        # Keep specialized list/table/linebreak handling below. Ordinary inline
        # tags can acquire a block outer box through an explicit display style.
        css_block = (not inline_container and tag not in {
            "html", "body", "[document]", "br", "hr", "ol", "ul", "li", "dl", "dt", "dd",
            "table", "thead", "tbody", "tfoot", "tr", "td", "th", "col", "colgroup", "caption",
        })
        if tag in self.HEADING_TAGS and not inline_container:
            fmt["heading_level"] = int(tag[1])
            fmt["bold"] = True
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n\n", formatting={"paragraph_break": True}))
            return

        # Paragraphs and block elements
        if css_block:
            align = node.get("align") or self._get_style_value(style, "text-align")
            if align:
                fmt["alignment"] = align.strip().lower()

            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n\n", formatting={"paragraph_break": True}))
            return

        # Line break
        if tag == "br":
            if fmt.get("preformatted"):
                # In a preserved run BR is content, just like a literal LF.
                # Keep it separate from generated block boundaries so blank
                # code lines survive next to a sibling paragraph.
                segments.append(TextSegment(text="\n", formatting=dict(fmt)))
            else:
                segments.append(TextSegment(text="\n", formatting={"linebreak": True, "explicit_break_count": 1}))
            return

        # Horizontal rule
        if tag == "hr":
            if visibility_hidden:
                segments.append(TextSegment(text="\n", formatting={"linebreak": True}))
            else:
                segments.append(TextSegment(text="\n---\n", formatting={"horizontal_rule": True}))
            return

        # Lists
        if tag == self.ORDERED_LIST_TAG:
            step = -1 if node.has_attr("reversed") else 1
            default_start = (sum(self._has_list_marker(child) for child in node.find_all("li", recursive=False))
                             if step < 0 else 1)
            try:
                start = int(node.get("start", default_start))
            except (TypeError, ValueError):
                start = default_start
            counter = [start - step, step, node.get("type", "1")]
            if not inline_container:
                segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context="numbered", list_counter=counter)
            if not inline_container:
                segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        if tag == self.UNORDERED_LIST_TAG:
            if not inline_container:
                segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context="bulleted", list_counter=None)
            if not inline_container:
                segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        if tag == self.LIST_ITEM_TAG:
            list_marker = self._has_list_marker(node)
            prefix = ""
            if list_marker and list_context == "numbered" and list_counter is not None:
                step = list_counter[1]
                try:
                    list_counter[0] = int(node["value"]) if node.has_attr("value") else list_counter[0] + step
                except (TypeError, ValueError):
                    list_counter[0] += step
                marker_type = node.get("type", list_counter[2])
                prefix = f"{self._ordered_marker(list_counter[0], marker_type)}. "
                fmt["list_type"] = "numbered"
                fmt["list_index"] = list_counter[0]
            elif list_marker:
                prefix = "- "
                fmt["list_type"] = "bulleted"

            if not inline_container:
                segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            if not visibility_hidden and list_marker:
                segments.append(TextSegment(text=prefix, formatting=dict(fmt, list_prefix=True)))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            if not inline_container:
                segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        # Table elements
        if tag == "table":
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        if tag == "tr":
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n", formatting={"linebreak": True}))
            return

        if tag in ("td", "th"):
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            # Tab separator between cells
            segments.append(TextSegment(text=" ", formatting={}))
            return

        # Definition lists
        if tag == "dl":
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        if tag == "dt":
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n", formatting={"linebreak": True}))
            return

        if tag == "dd":
            segments.append(TextSegment(text="  ", formatting={}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n", formatting={"linebreak": True}))
            return

        # Default: recurse into children
        for child in node.children:
            self._walk_node(child, fmt, segments, list_context, list_counter)

    @staticmethod
    def _ordered_marker(number: int, marker_type: str) -> str:
        """Render HTML's decimal, alphabetic, and Roman ordered-list markers."""
        if marker_type in ("a", "A") and number > 0:
            letters = []
            while number:
                number, remainder = divmod(number - 1, 26)
                letters.append(chr(ord("a") + remainder))
            marker = "".join(reversed(letters))
            return marker.upper() if marker_type == "A" else marker
        if marker_type in ("i", "I") and 0 < number < 4000:
            parts = []
            for value, letters in ((1000, "M"), (900, "CM"), (500, "D"),
                                   (400, "CD"), (100, "C"), (90, "XC"),
                                   (50, "L"), (40, "XL"), (10, "X"),
                                   (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
                count, number = divmod(number, value)
                parts.append(letters * count)
            marker = "".join(parts)
            return marker.lower() if marker_type == "i" else marker
        return str(number)

    def _apply_inline_styles(self, style: str, fmt: dict) -> None:
        """Extract relevant CSS properties from an inline style string."""
        color = self._get_style_value(style, "color")
        if color:
            fmt["color"] = color.strip()

        bg = self._get_style_value(style, "background-color")
        if bg:
            fmt["background_color"] = bg.strip()

        weight = self._get_style_value(style, "font-weight")
        if weight and (weight.strip() in ("bold", "700", "800", "900")):
            fmt["bold"] = True

        fs = self._get_style_value(style, "font-style")
        if fs and fs.strip() == "italic":
            fmt["italic"] = True

        td = self._get_style_value(style, "text-decoration")
        if td and "underline" in td:
            fmt["underline"] = True

        align = self._get_style_value(style, "text-align")
        if align:
            fmt["alignment"] = align.strip().lower()

        font_size = self._get_style_value(style, "font-size")
        if font_size:
            fmt["font_size"] = font_size.strip()

    @staticmethod
    def _get_style_value(style: str, prop: str) -> Optional[str]:
        """Extract a single CSS property value from a style string."""
        pattern = rf"{re.escape(prop)}\s*:\s*([^;]+)"
        match = re.search(pattern, style, re.IGNORECASE)
        return match.group(1).strip() if match else None

    @staticmethod
    def _clean_segments(segments: list[TextSegment]) -> list[TextSegment]:
        """Remove redundant whitespace segments, normalize, and merge into plain text."""
        cleaned: list[TextSegment] = []
        for seg in segments:
            # Skip empty text segments
            if not seg.text:
                continue

            is_break = seg.formatting.get("paragraph_break") or seg.formatting.get("linebreak")
            preserved = seg.formatting.get("preformatted")
            if is_break:
                # Source indentation between blocks is not visible HTML text.
                while (cleaned and not cleaned[-1].text.strip(" \t\r\n\f")
                       and not cleaned[-1].formatting.get("paragraph_break")
                       and not cleaned[-1].formatting.get("linebreak")
                       and not cleaned[-1].formatting.get("preformatted")):
                    cleaned.pop()
            elif not preserved and not seg.text.strip(" \t\r\n\f"):
                if not cleaned or cleaned[-1].formatting.get("paragraph_break") or cleaned[-1].formatting.get("linebreak"):
                    continue

            # Collapse consecutive paragraph/linebreak breaks
            if (
                (seg.formatting.get("paragraph_break") or seg.formatting.get("linebreak"))
                and cleaned
                and (cleaned[-1].formatting.get("paragraph_break") or cleaned[-1].formatting.get("linebreak"))
            ):
                explicit = cleaned[-1].formatting.get("explicit_break_count", 0) + seg.formatting.get("explicit_break_count", 0)
                if explicit:
                    # Keep only the largest structural separator here. Building
                    # the growing explicit BR string on every tag is quadratic.
                    if len(seg.text) > len(cleaned[-1].text):
                        cleaned[-1].text = seg.text
                    cleaned[-1].formatting = {"linebreak": True, "explicit_break_count": explicit}
                    continue
                # Keep the stronger break (paragraph > linebreak)
                if seg.formatting.get("paragraph_break") and (not cleaned[-1].formatting.get("paragraph_break") or len(seg.text) > len(cleaned[-1].text)):
                    cleaned[-1] = seg
                continue

            cleaned.append(seg)

        # Strip leading/trailing whitespace-only segments
        while cleaned and cleaned[0].text.strip(" \t\r\n\f") == "" and cleaned[0].formatting.get("paragraph_break") and not cleaned[0].formatting.get("explicit_break_count"):
            cleaned.pop(0)
        while (cleaned and not cleaned[-1].text.strip(" \t\r\n\f")
               and not cleaned[-1].formatting.get("preformatted")
               and not cleaned[-1].formatting.get("linebreak")):
            cleaned.pop()

        # Strip trailing whitespace from segments before breaks
        for i in range(len(cleaned) - 1):
            if not cleaned[i].formatting.get("preformatted") and (cleaned[i + 1].formatting.get("paragraph_break") or cleaned[i + 1].formatting.get("linebreak")):
                cleaned[i].text = cleaned[i].text.rstrip(" \t\r\n\f")

        # Merge adjacent text segments into larger plain-text chunks.
        merged: list[TextSegment] = []
        inline_runs: list[tuple[bool, list[str]]] = []

        def flush_inline() -> None:
            if inline_runs:
                # CSS whitespace changes within one paragraph must not become
                # separate planner paragraphs. Normalize only collapsible runs,
                # then join the whole inline region in linear work.
                parts = []
                for preserve, values in inline_runs:
                    part = "".join(values)
                    if not preserve:
                        part = re.sub(r" *\n *", "\n", re.sub(r"[ \t\f]+", " ", part))
                    parts.append(part)
                if not inline_runs[0][0]:
                    parts[0] = parts[0].lstrip(" ")
                if not inline_runs[-1][0]:
                    parts[-1] = parts[-1].rstrip(" ")
                fmt = ({"preformatted": True}
                       if any(preserve for preserve, _ in inline_runs) or any("\n" in part for part in parts)
                       else {})
                merged.append(TextSegment(text="".join(parts), formatting=fmt))
                inline_runs.clear()

        for seg in cleaned:
            is_break = seg.formatting.get("paragraph_break") or seg.formatting.get("linebreak")
            if is_break:
                flush_inline()
                merged.append(seg)
                continue
            # Normal and pre-line both collapse spaces, including at their
            # shared inline boundary. Only true pre modes split those runs.
            preserve = bool(seg.formatting.get("preformatted")
                            and seg.formatting.get("_white_space") != "pre-line")
            if not inline_runs or inline_runs[-1][0] != preserve:
                inline_runs.append((preserve, []))
            inline_runs[-1][1].append(seg.text)
        flush_inline()

        # HTML whitespace at block edges does not produce visible content.
        for i, seg in enumerate(merged):
            if not (seg.formatting.get("paragraph_break") or seg.formatting.get("linebreak") or seg.formatting.get("preformatted")):
                if i == 0 or merged[i - 1].formatting.get("paragraph_break") or merged[i - 1].formatting.get("linebreak"):
                    seg.text = seg.text.lstrip(" ")
                if i == len(merged) - 1 or merged[i + 1].formatting.get("paragraph_break") or merged[i + 1].formatting.get("linebreak"):
                    seg.text = seg.text.rstrip(" ")
        # Generated block separators disappear at the document edges, while
        # explicit BR elements remain actual user-visible newlines.
        for index, seg in enumerate(merged):
            explicit = seg.formatting.pop("explicit_break_count", 0)
            if explicit:
                count = explicit if index in (0, len(merged) - 1) else max(explicit, len(seg.text))
                seg.text = "\n" * count
        return [seg for seg in merged if seg.text]
