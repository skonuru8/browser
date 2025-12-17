"""CSS parsing, selector matching and styling functions.

This module defines a tiny subset of CSS needed for the toy browser. It
supports simple tag and descendant selectors and parses property/value
pairs. The :func:`style` function walks a DOM tree, applying the
appropriate styles inherited from the user agent stylesheet and any
author styles.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .dom import Element, Text


class TagSelector:
    """Selects elements by tag name."""
    def __init__(self, tag: str) -> None:
        self.tag = tag
        # Priority for CSS cascade: simple tag selectors have weight 1
        self.priority = 1

    def matches(self, node: Any) -> bool:
        return isinstance(node, Element) and self.tag == node.tag


class DescendantSelector:
    """Matches elements that are descendants of a given ancestor selector."""
    def __init__(self, ancestor: TagSelector | 'DescendantSelector', descendant: TagSelector) -> None:
        self.ancestor = ancestor
        self.descendant = descendant
        # Sum the priorities to determine cascade order
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node: Any) -> bool:
        # First ensure the descendant selector matches this node
        if not self.descendant.matches(node):
            return False
        # Then walk up the parent chain looking for an ancestor match
        parent = getattr(node, 'parent', None)
        while parent:
            if self.ancestor.matches(parent):
                return True
            parent = getattr(parent, 'parent', None)
        return False


class CSSParser:
    """Parse a simple CSS stylesheet into a list of (selector, properties) tuples."""
    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0

    def whitespace(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def literal(self, literal: str) -> None:
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception(f"Expected '{literal}'")
        self.i += 1

    def word(self) -> str:
        start = self.i
        while self.i < len(self.s) and (
            self.s[self.i].isalnum() or self.s[self.i] in "#-.%"
        ):
            self.i += 1
        if not (self.i > start):
            raise Exception("Expected word")
        return self.s[start:self.i]

    def ignore_until(self, chars: List[str]) -> str | None:
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            self.i += 1
        return None

    def pair(self) -> Tuple[str, str]:
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()
        return prop.casefold(), val

    def body(self) -> Dict[str, str]:
        pairs: Dict[str, str] = {}
        while self.i < len(self.s) and self.s[self.i] != "}":
            try:
                prop, val = self.pair()
                pairs[prop] = val
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except Exception:
                # Skip malformed declarations
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs

    def selector(self) -> TagSelector | DescendantSelector:
        out: TagSelector | DescendantSelector = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            tag = self.word().casefold()
            descendant = TagSelector(tag)
            out = DescendantSelector(out, descendant)
            self.whitespace()
        return out

    def parse(self) -> List[Tuple[Any, Dict[str, str]]]:
        rules: List[Tuple[Any, Dict[str, str]]] = []
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal("{")
                self.whitespace()
                body = self.body()
                self.literal("}")
                rules.append((selector, body))
            except Exception:
                # Skip malformed rules
                why = self.ignore_until(["}"])
                if why == "}":
                    self.literal("}")
                    self.whitespace()
                else:
                    break
        return rules


def cascade_priority(rule: Tuple[Any, Dict[str, str]]) -> int:
    selector, _ = rule
    return selector.priority


# Default user agent stylesheet: a list of (selector, properties) tuples
DEFAULT_STYLE_SHEET: List[Tuple[Any, Dict[str, str]]] = [
    (TagSelector("body"), {"background-color": "white", "color": "black"}),
    (TagSelector("pre"),  {"background-color": "gray"}),
    (DescendantSelector(TagSelector("body"), TagSelector("a")), {"color": "blue"}),
    # Widgets
    (TagSelector("input"),  {"font-size": "16px", "font-weight": "normal", "font-style": "normal",
                             "background-color": "lightblue", "color": "black"}),
    (TagSelector("button"), {"font-size": "16px", "font-weight": "normal", "font-style": "normal",
                             "background-color": "orange", "color": "black"}),
    # Hide script and style contents from rendering
    (TagSelector("script"), {"display": "none"}),
    (TagSelector("style"),  {"display": "none"}),
    (TagSelector("i"),    {"font-style": "italic"}),
    (TagSelector("b"),    {"font-weight": "bold"}),
    (TagSelector("small"),{"font-size": "90%"}),
    (TagSelector("big"),  {"font-size": "110%"}),
]


# Properties that inherit from parent to child and their defaults
INHERITED_PROPERTIES: Dict[str, str] = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "color": "black",
}


def style(node: Any, rules: List[Tuple[Any, Dict[str, str]]]) -> None:
    """Recursively apply styles to the DOM tree based on CSS rules."""
    # Start with inherited properties
    node.style = {}
    for prop, default_value in INHERITED_PROPERTIES.items():
        if getattr(node, 'parent', None):
            node.style[prop] = getattr(node.parent, 'style', {}).get(prop, default_value)
        else:
            node.style[prop] = default_value
    # Apply matching rules
    for selector, body in rules:
        try:
            if selector.matches(node):
                for p, v in body.items():
                    node.style[p] = v
        except Exception:
            # If a selector errors out, ignore it
            continue
    # Convert percentage font sizes to pixels based on parent
    if node.style.get("font-size", "").endswith("%"):
        try:
            parent_px = float((getattr(node.parent, 'style', {}).get("font-size", INHERITED_PROPERTIES["font-size"]))[:-2])
            pct = float(node.style["font-size"][:-1]) / 100.0
            node.style["font-size"] = str(pct * parent_px) + "px"
        except Exception:
            node.style["font-size"] = INHERITED_PROPERTIES["font-size"]
    # Recurse into children
    for c in getattr(node, 'children', []):
        style(c, rules)
