"""DOM definitions for the simple browser.

This module contains the DOM node classes (:class:`Text` and
:class:`Element`) as well as a small HTML parser that builds a tree
from raw HTML strings. It also provides helper functions for
traversing and inspecting the tree.
"""

from __future__ import annotations

from typing import List, Dict, Tuple, Optional, Any


class Text:
    """A leaf node representing a run of text in the DOM."""
    def __init__(self, text: str, parent: Optional['Element']) -> None:
        self.text: str = text
        self.children: List[Any] = []
        self.parent: Optional[Element] = parent
        # Style dictionary populated during styling
        self.style: Dict[str, str] = {}
        # Whether this node currently has focus (used for inputs)
        self.is_focused: bool = False

    def __repr__(self) -> str:
        return repr(self.text)


class Element:
    """A node representing an HTML element and its children."""
    def __init__(self, tag: str, attributes: Dict[str, str], parent: Optional['Element']) -> None:
        self.tag: str = tag
        self.attributes: Dict[str, str] = attributes
        self.children: List[Any] = []
        self.parent: Optional[Element] = parent
        self.style: Dict[str, str] = {}
        self.is_focused: bool = False

    def __repr__(self) -> str:
        return "<" + self.tag + ">"


def print_tree(node: Any, indent: int = 0) -> None:
    """Recursively print the DOM tree starting at ``node``."""
    print("  " * indent + repr(node))
    for c in getattr(node, "children", []):
        print_tree(c, indent + 1)


def tree_to_list(tree: Any, out: List[Any]) -> List[Any]:
    """Flatten the DOM tree into a list using preorder traversal."""
    out.append(tree)
    for c in getattr(tree, "children", []):
        tree_to_list(c, out)
    return out


class HTMLParser:
    """A very small HTML parser supporting tag and text nodes.

    The parser builds a tree of :class:`Text` and :class:`Element`
    objects. It also implicitly inserts ``<html>``, ``<head>`` and
    ``<body>`` elements when they are omitted from the document.
    Contents of ``<script>`` and ``<style>`` tags are suppressed to
    avoid rendering them as part of the visible page.
    """

    # Tags that automatically close themselves (no closing tag)
    SELF_CLOSING_TAGS = [
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    ]
    # Tags that may only appear in the <head>
    HEAD_TAGS = [
        "base", "basefont", "bgsound", "noscript",
        "link", "meta", "title", "style", "script",
    ]

    def __init__(self, body: str) -> None:
        self.body: str = body
        # Stack of open elements
        self.unfinished: List[Any] = []

    def parse(self) -> Any:
        """Parse the HTML and return the root node."""
        text = ""
        in_tag = False
        for c in self.body:
            if c == "<":
                in_tag = True
                if text:
                    self.add_text(text)
                    text = ""
            elif c == ">":
                in_tag = False
                self.add_tag(text)
                text = ""
            else:
                text += c
        if not in_tag and text:
            self.add_text(text)
        return self.finish()

    def get_attributes(self, text: str) -> Tuple[str, Dict[str, str]]:
        parts = text.split()
        if not parts:
            return "", {}
        tag = parts[0].casefold()
        attributes: Dict[str, str] = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.casefold()] = value
            else:
                attributes[attrpair.casefold()] = ""
        return tag, attributes

    def implicit_tags(self, tag: Optional[str]) -> None:
        """Automatically insert <html>, <head>, and <body> tags if needed."""
        while True:
            open_tags = [node.tag for node in self.unfinished if isinstance(node, Element)]
            if open_tags == [] and tag != "html":
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS:
                self.add_tag("/head")
            else:
                break

    def add_text(self, text: str) -> None:
        """Add a text node to the current parent element, skipping script/style."""
        if text.isspace():
            return
        # Skip text inside <script> or <style>
        for ancestor in self.unfinished:
            if isinstance(ancestor, Element) and ancestor.tag in ("script", "style"):
                return
        # Ensure implicit <html>/<body>
        self.implicit_tags(None)
        parent = self.unfinished[-1] if self.unfinished else None
        if parent is None:
            self.implicit_tags(None)
            parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    def add_tag(self, tagtext: str) -> None:
        if tagtext.startswith("!"):
            return
        tag, attributes = self.get_attributes(tagtext)
        self.implicit_tags(tag)
        if tag.startswith("/"):
            # Closing tag: pop the stack and attach to parent
            if len(self.unfinished) == 1:
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        elif tag in self.SELF_CLOSING_TAGS:
            parent = self.unfinished[-1] if self.unfinished else None
            if parent is None:
                self.implicit_tags(tag)
                parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def finish(self) -> Any:
        """Finish parsing by closing any still-open tags and returning the root."""
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()
