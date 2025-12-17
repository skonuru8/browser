"""Layout and drawing primitives for the simple browser.

This module implements the box model, computes positions and sizes for
DOM elements, and produces a display list of drawing commands. It also
defines simple geometry and drawing helper classes (``Rect``,
``DrawText``, ``DrawRect``, etc.) and a function to walk the layout
tree and collect paint instructions.

Portions of the implementation are adapted from the original
monolithic browser, but reorganized into a separate module. Some
functions refer to the :class:`Browser` class at runtime; the browser
module will inject the Browser class into this module so that hit
testing works without a circular import.
"""

from __future__ import annotations

import tkinter
import tkinter.font
from typing import Any, List, Tuple, Optional, Dict

# Import DOM types and inherited CSS properties
from dom import Text, Element
from css import INHERITED_PROPERTIES


# Font cache: keyed by (size, weight, style) → tkinter.font.Font
FONTS: Dict[Tuple[int, str, str], tkinter.font.Font] = {}


def get_font(size: int, weight: str, style: str) -> tkinter.font.Font:
    """Return a cached tkinter Font for the given characteristics."""
    key = (size, weight, style)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=style)
        # The label is unused here, but historically a label was created to
        # measure text metrics. The font object itself suffices.
        FONTS[key] = font
    return FONTS[key]


# Layout constants
WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
SCROLLBAR_WIDTH = 12
INPUT_WIDTH_PX = 200
CHECKBOX_SIZE = 16

# Block-level elements as per simplified HTML specification
BLOCK_ELEMENTS: List[str] = [
    "html", "body", "article", "section", "nav", "aside",
    "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "header",
    "footer", "address", "p", "hr", "pre", "blockquote",
    "ol", "ul", "menu", "li", "dl", "dt", "dd", "figure",
    "figcaption", "main", "div", "table", "form", "fieldset",
    "legend", "details", "summary"
]


class DocumentLayout:
    """Top-level layout object that anchors the page."""
    def __init__(self, node: Any) -> None:
        self.node = node
        self.parent: Optional[Any] = None
        self.children: List[Any] = []
        self.x = self.y = self.width = self.height = None

    def layout(self) -> None:
        child = BlockLayout(self.node, self, None)
        self.children = [child]
        # The document takes up the full available width minus margins and scrollbar
        self.width = WIDTH - 2 * HSTEP - SCROLLBAR_WIDTH
        self.x = HSTEP
        self.y = VSTEP
        child.layout()
        self.height = child.height

    def paint(self) -> List[Any]:
        return []

    def should_paint(self) -> bool:
        return True


class BlockLayout:
    """Layout object for block-level and inline content.

    Each BlockLayout corresponds to a DOM node. Depending on the
    node's structure and children, it either creates child block
    layouts (for elements with block descendants) or an inline display
    list representing runs of text and widgets. It also registers
    clickable widget boxes via :class:`Browser` for hit-testing.
    """
    def __init__(self, node: Any, parent: Any, previous: Optional['BlockLayout']) -> None:
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children: List[Any] = []
        # Inline display items: tuples describing what to draw
        self.display_list: List[Tuple] = []
        # Position and size
        self.x = self.y = self.width = self.height = None
        # Cursor state for inline content
        self.cursor_x = self.cursor_y = 0
        # Line buffer for inline words
        self.line: List[Tuple] = []

    def layout_mode(self) -> str:
        if isinstance(self.node, Text):
            return "inline"
        elif any(isinstance(c, Element) and c.tag in BLOCK_ELEMENTS for c in getattr(self.node, 'children', [])):
            return "block"
        elif getattr(self.node, 'children', []) or (isinstance(self.node, Element) and self.node.tag in ["input", "button"]):
            return "inline"
        else:
            return "block"

    def layout(self) -> None:
        # Position relative to parent and previous sibling
        self.x = getattr(self.parent, 'x', 0)
        self.width = getattr(self.parent, 'width', WIDTH)
        self.y = (self.previous.y + self.previous.height) if self.previous else getattr(self.parent, 'y', 0)
        mode = self.layout_mode()
        if mode == "block":
            prev: Optional['BlockLayout'] = None
            for c in getattr(self.node, 'children', []):
                child = BlockLayout(c, self, prev)
                self.children.append(child)
                prev = child
        else:
            # Inline mode: build a single display list
            self.cursor_x = 0
            self.cursor_y = 0
            self.line = []
            self.recurse(self.node)
            self.flush()
        # Layout children recursively
        for c in self.children:
            c.layout()
        # Compute total height
        if mode == "block":
            self.height = sum(ch.height for ch in self.children) if self.children else VSTEP
        else:
            # Determine the bottom-most pixel used by inline content
            last_y = self.y
            for it in reversed(self.display_list):
                tag = it[0] if isinstance(it, tuple) and it and isinstance(it[0], str) else None
                if tag in ("text", "text_abs"):
                    last_y = it[1][1]
                    break
                elif tag in ("rect", "outline"):
                    last_y = it[1][3]
                    break
                elif tag == "line":
                    last_y = max(it[1][1], it[1][3])
                    break
                # Legacy tuple support
                if tag is None and len(it) >= 2 and isinstance(it[1], (int, float)):
                    last_y = it[1]
                    break
            # Default font for computing line spacing
            default_font = get_font(12, "normal", "roman")
            self.height = max((last_y - self.y) + default_font.metrics("linespace"), VSTEP)

    def recurse(self, node: Any) -> None:
        if isinstance(node, Text):
            for w in node.text.split():
                self.word(node, w)
        else:
            if isinstance(node, Element) and node.tag in ["input", "button", "br"]:
                if node.tag == "br":
                    self.flush()
                else:
                    self.input(node)
            else:
                for c in getattr(node, 'children', []):
                    self.recurse(c)

    def word(self, node: Any, word: str) -> None:
        # Determine font from CSS styles
        weight = node.style.get("font-weight", "normal")
        style = node.style.get("font-style", "normal")
        if style == "normal":
            style = "roman"
        size_value = node.style.get("font-size", INHERITED_PROPERTIES["font-size"])
        try:
            px = float(size_value[:-2])
        except Exception:
            px = float(INHERITED_PROPERTIES["font-size"][:-2])
        size = int(px * 0.75)
        font = get_font(size, weight, style)
        color = node.style.get("color", "black")
        w = font.measure(word)
        # New line if word would overflow
        if self.cursor_x + w > self.width and self.line:
            self.flush()
        # Append item to line buffer
        self.line.append(("text", self.cursor_x, word, font, color, node))
        # Advance cursor
        self.cursor_x += w + font.measure(" ")

    def input(self, node: Any) -> None:
        # Determine input type; default to text
        itype = node.attributes.get("type", "text").lower() if isinstance(node, Element) else "text"
        # Hidden inputs take no space
        if itype == "hidden":
            return
        # Determine font
        weight = node.style.get("font-weight", "normal")
        style = node.style.get("font-style", "normal")
        if style == "normal":
            style = "roman"
        try:
            size = int(float(node.style.get("font-size", INHERITED_PROPERTIES["font-size"])[:-2]) * 0.75)
        except Exception:
            size = int(float(INHERITED_PROPERTIES["font-size"][:-2]) * 0.75)
        font = get_font(size, weight, style)
        is_checkbox = itype == "checkbox"
        # Compute width of the input or button
        if is_checkbox:
            w = CHECKBOX_SIZE
        elif isinstance(node, Element) and node.tag == "input":
            w = INPUT_WIDTH_PX
        else:
            # Button: width based on its label text
            text = self.button_label(node)
            w = max(80, font.measure(text) + 20)
        # Wrap if necessary
        if self.cursor_x + w > self.width:
            self.flush()
        metrics = font.metrics()
        max_ascent = metrics["ascent"]
        baseline = self.cursor_y + max_ascent
        x = self.x + self.cursor_x
        y_top = self.y + baseline - font.metrics("ascent")
        y_bottom = y_top + (CHECKBOX_SIZE if is_checkbox else font.metrics("linespace"))
        rect = (x, y_top, x + w, y_bottom)
        # Register widget box for hit testing
        # The Browser class will be injected into this module by project.browser
        try:
            # type: ignore[name-defined]
            Browser._register_widget_box(node, rect)  # noqa: F821
        except Exception:
            pass
        # Draw background or checkbox outline
        if is_checkbox:
            # Checkbox background and border
            self.display_list.append(("rect", rect, "#e6f2ff"))
            self.display_list.append(("outline", rect, "black", 1))
            # Draw check mark if checked
            checked = ("checked" in node.attributes) or (node.attributes.get("_checked_state") == "true") if isinstance(node, Element) else False
            if checked:
                self.display_list.append(("line", (x + 3, y_top + 3, x + w - 3, y_bottom - 3, "black", 2)))
                self.display_list.append(("line", (x + w - 3, y_top + 3, x + 3, y_bottom - 3, "black", 2)))
        else:
            bgcolor = node.style.get("background-color", "transparent")
            if bgcolor != "transparent":
                self.display_list.append(("rect", rect, bgcolor))
            # Determine text for input or button
            if isinstance(node, Element) and node.tag == "input":
                raw = node.attributes.get("value", "")
                if itype == "password":
                    text = "".join("•" for _ in raw)
                else:
                    text = raw
            else:
                text = self.button_label(node)
            color = node.style.get("color", "black")
            self.display_list.append(("text_abs", (x, y_top), text, font, color))
            if getattr(node, 'is_focused', False) and isinstance(node, Element) and node.tag == "input":
                cx = x + font.measure(text)
                self.display_list.append(("line", (cx, y_top, cx, y_bottom, "black", 1)))
        # Advance cursor
        self.cursor_x += w + font.measure(" ")

    def button_label(self, node: Any) -> str:
        if isinstance(node, Element) and len(node.children) == 1 and isinstance(node.children[0], Text):
            return node.children[0].text
        return ""

    def flush(self) -> None:
        """Flush the current line buffer to the display list."""
        if not self.line:
            return
        metrics_list = [itm[3].metrics() for itm in self.line]
        max_ascent = max(m["ascent"] for m in metrics_list)
        max_descent = max(m["descent"] for m in metrics_list)
        baseline = self.cursor_y + max_ascent
        for kind, rel_x, word, font, color, node in self.line:
            x = self.x + rel_x
            y = self.y + baseline - font.metrics("ascent")
            self.display_list.append(("text_abs", (x, y), word, font, color))
            # Register hyperlink hit boxes
            link = node
            while link and not (isinstance(link, Element) and link.tag == "a"):
                link = getattr(link, 'parent', None)
            if link and isinstance(link, Element) and "href" in link.attributes:
                width = font.measure(word)
                height = font.metrics("linespace")
                rect = (x, y, x + width, y + height)
                try:
                    # type: ignore[name-defined]
                    Browser._register_widget_box(link, rect)  # noqa: F821
                except Exception:
                    pass
        # Move to next line
        self.cursor_y = baseline + int(1.25 * max_descent)
        self.cursor_x = 0
        self.line = []

    # Optional helpers for API compatibility
    def new_line(self) -> None:
        self.flush()

    def self_rect(self) -> 'Rect':
        try:
            right = self.x + (self.width or 0)
            bottom = self.y + (self.height or 0)
        except Exception:
            right = self.x or 0
            bottom = self.y or 0
        return Rect(self.x or 0, self.y or 0, right, bottom)

    def should_paint(self) -> bool:
        if isinstance(self.node, Element) and self.node.tag in ["input", "button"]:
            return False
        return True

    def paint(self) -> List[Any]:
        cmds: List[Any] = []
        if isinstance(self.node, Element) and self.node.tag == "pre":
            x2, y2 = self.x + self.width, self.y + self.height
            cmds.append(DrawRect(self.x, self.y, x2, y2, "gray"))
        for item in self.display_list:
            if item[0] == "text_abs":
                _, (x, y), word, font, color = item
                cmds.append(DrawText(x, y, word, font, color))
            elif item[0] == "rect":
                _, (x1, y1, x2, y2), color = item
                cmds.append(DrawRect(x1, y1, x2, y2, color))
            elif item[0] == "line":
                _, (x1, y1, x2, y2, color, th) = item
                cmds.append(DrawLine(x1, y1, x2, y2, color, th))
            elif item[0] == "outline":
                _, (x1, y1, x2, y2), color, th = item
                cmds.append(DrawOutline(x1, y1, x2, y2, color, th))
        return cmds


class Rect:
    """Axis-aligned rectangle used for hit testing."""
    def __init__(self, left: float, top: float, right: float, bottom: float) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def contains_point(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


class DrawText:
    """Draw a string at a fixed position."""
    def __init__(self, x1: float, y1: float, text: str, font: tkinter.font.Font, color: str) -> None:
        self.left = x1
        self.top = y1
        self.text = text
        self.font = font
        self.color = color

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_text(self.left, self.top - scroll, text=self.text, font=self.font, fill=self.color, anchor='nw')


class DrawRect:
    """Draw a filled rectangle."""
    def __init__(self, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
        self.left = x1
        self.top = y1
        self.right = x2
        self.bottom = y2
        self.color = color

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_rectangle(self.left, self.top - scroll, self.right, self.bottom - scroll, width=0, fill=self.color)


class DrawLine:
    """Draw a straight line with optional thickness."""
    def __init__(self, x1: float, y1: float, x2: float, y2: float, color: str, thickness: int = 1) -> None:
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.color = color
        self.thickness = thickness

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_line(self.x1, self.y1 - scroll, self.x2, self.y2 - scroll, fill=self.color, width=self.thickness)


class DrawOutline:
    """Draw the outline of a rectangle."""
    def __init__(self, x1: float, y1: float, x2: float, y2: float, color: str, thickness: int = 1) -> None:
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.color = color
        self.thickness = thickness

    def execute(self, scroll: float, canvas: tkinter.Canvas) -> None:
        canvas.create_rectangle(self.x1, self.y1 - scroll, self.x2, self.y2 - scroll, outline=self.color, width=self.thickness)


def paint_tree(layout_object: Any, display_list: List[Any]) -> None:
    """Walk the layout tree and collect drawing commands."""
    if hasattr(layout_object, "should_paint") and not layout_object.should_paint():
        pass
    else:
        display_list.extend(layout_object.paint())
    for child in getattr(layout_object, 'children', []):
        paint_tree(child, display_list)
