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
    BLOCK_TAGS = {"p", "div", "blockquote", "section", "article", "header", "footer"}
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
            except Exception:
                logger.exception("HTML parsing failed, falling back to plain text")

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
    STRIP_TAGS = {"script", "style", "noscript", "svg", "math", "head", "title", "meta", "link", "base"}

    # Regex for citation-like <sup> content: [1], [a], [1][2], [edit], etc.
    _SUP_CITATION_RE = re.compile(r"^\s*\[[\d\w,\s]+\]\s*$")

    def _parse_html(self, html: str) -> list[TextSegment]:
        """Parse HTML content into plain-text TextSegments.

        Strips all formatting (bold, italic, links, colors) so the typed text
        inherits the destination's style. Also removes citation markers like [1][2].
        """
        soup = BeautifulSoup(html, "html.parser")

        # Strip tags that should always be removed
        for tag in soup.find_all(self.STRIP_TAGS):
            # Removing a head also removes its descendants; skip detached
            # metadata instead of trying to replace it a second time.
            if tag.parent is None:
                continue
            tag.replace_with(" ")

        # Strip citation <sup> tags specifically (preserve legitimate superscripts like x²)
        for sup in soup.find_all("sup"):
            classes = sup.get("class", [])
            text_content = sup.get_text()
            if ("reference" in classes or "noprint" in classes
                    or self._SUP_CITATION_RE.match(text_content)):
                sup.replace_with(" ")

        body = soup.body if soup.body else soup
        segments: list[TextSegment] = []
        self._walk_node(body, {}, segments, list_context=None, list_counter=None)

        # Strip all formatting from segments — we only want plain text
        for seg in segments:
            seg.formatting = {k: v for k, v in seg.formatting.items()
                              if k in ("paragraph_break", "linebreak", "list_type",
                                       "list_index", "list_prefix", "heading_level", "preformatted",
                                       "explicit_break_count")}

        return self._clean_segments(segments)

    def _walk_node(
        self,
        node: Tag | NavigableString,
        inherited_fmt: dict,
        segments: list[TextSegment],
        list_context: Optional[str],
        list_counter: Optional[list[int]],
    ) -> None:
        """Recursively walk the DOM tree building TextSegments."""
        if isinstance(node, (Comment, Declaration, Doctype, ProcessingInstruction)):
            return
        if isinstance(node, NavigableString):
            text = str(node)
            # Collapse whitespace first (handles "\n  " from prettified HTML)
            collapsed = re.sub(r"\s+", " ", text)
            # Normalize non-breaking spaces
            collapsed = collapsed.replace("\u00a0", " ")
            if collapsed.strip() or collapsed == " ":
                if collapsed:
                    segments.append(TextSegment(text=collapsed, formatting=dict(inherited_fmt)))
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower() if node.name else ""
        fmt = dict(inherited_fmt)

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

        # Headings
        if tag in self.HEADING_TAGS:
            fmt["heading_level"] = int(tag[1])
            fmt["bold"] = True
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n\n", formatting={"paragraph_break": True}))
            return

        # Paragraphs and block elements
        if tag in self.BLOCK_TAGS:
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
            segments.append(TextSegment(text="\n", formatting={"linebreak": True, "explicit_break_count": 1}))
            return

        # Horizontal rule
        if tag == "hr":
            segments.append(TextSegment(text="\n---\n", formatting={"horizontal_rule": True}))
            return

        # Lists
        if tag == self.ORDERED_LIST_TAG:
            step = -1 if node.has_attr("reversed") else 1
            default_start = len(node.find_all("li", recursive=False)) if step < 0 else 1
            try:
                start = int(node.get("start", default_start))
            except (TypeError, ValueError):
                start = default_start
            counter = [start - step, step]
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context="numbered", list_counter=counter)
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        if tag == self.UNORDERED_LIST_TAG:
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context="bulleted", list_counter=None)
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            return

        if tag == self.LIST_ITEM_TAG:
            if list_context == "numbered" and list_counter is not None:
                step = list_counter[1]
                try:
                    list_counter[0] = int(node["value"]) if node.has_attr("value") else list_counter[0] + step
                except (TypeError, ValueError):
                    list_counter[0] += step
                prefix = f"{list_counter[0]}. "
                fmt["list_type"] = "numbered"
                fmt["list_index"] = list_counter[0]
            else:
                prefix = "- "
                fmt["list_type"] = "bulleted"

            segments.append(TextSegment(text=prefix, formatting=dict(fmt, list_prefix=True)))
            for child in node.children:
                self._walk_node(child, fmt, segments, list_context, list_counter)
            segments.append(TextSegment(text="\n", formatting={"linebreak": True}))
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

        # Pre-formatted / code block
        if tag == "pre":
            fmt["preformatted"] = True
            text = node.get_text()
            segments.append(TextSegment(text="\n", formatting={"paragraph_break": True}))
            segments.append(TextSegment(text=text, formatting=dict(fmt)))
            segments.append(TextSegment(text="\n\n", formatting={"paragraph_break": True}))
            return

        # Default: recurse into children
        for child in node.children:
            self._walk_node(child, fmt, segments, list_context, list_counter)

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
                while (cleaned and not cleaned[-1].text.strip()
                       and not cleaned[-1].formatting.get("paragraph_break")
                       and not cleaned[-1].formatting.get("linebreak")
                       and not cleaned[-1].formatting.get("preformatted")):
                    cleaned.pop()
            elif not preserved and not seg.text.strip():
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
        while cleaned and cleaned[0].text.strip() == "" and cleaned[0].formatting.get("paragraph_break") and not cleaned[0].formatting.get("explicit_break_count"):
            cleaned.pop(0)
        while (cleaned and not cleaned[-1].text.strip()
               and not cleaned[-1].formatting.get("preformatted")
               and not cleaned[-1].formatting.get("linebreak")):
            cleaned.pop()

        # Strip trailing whitespace from segments before breaks
        for i in range(len(cleaned) - 1):
            if not cleaned[i].formatting.get("preformatted") and (cleaned[i + 1].formatting.get("paragraph_break") or cleaned[i + 1].formatting.get("linebreak")):
                cleaned[i].text = cleaned[i].text.rstrip()

        # Merge adjacent text segments into larger plain-text chunks.
        merged: list[TextSegment] = []
        for seg in cleaned:
            is_break = seg.formatting.get("paragraph_break") or seg.formatting.get("linebreak")
            if is_break or seg.formatting.get("preformatted"):
                merged.append(seg)
                continue

            # If previous segment is also inline text, merge them
            if merged and not merged[-1].formatting.get("preformatted") and not merged[-1].formatting.get("paragraph_break") and not merged[-1].formatting.get("linebreak"):
                prev = merged[-1]
                # Inline boundaries have no implied spaces. Keep the DOM's
                # actual whitespace and collapse it across adjacent nodes.
                prev.text = re.sub(r" +", " ", prev.text + seg.text)
            else:
                merged.append(TextSegment(text=seg.text, formatting={}))

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
