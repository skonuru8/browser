"""Browser UI, tabs and chrome logic for the modular web browser.

This module contains the high‑level user interface for the toy browser.
It uses Tkinter to build a window with a tab strip, address bar, status
line and a canvas for rendering page content. The :class:`Browser`
manages multiple :class:`Tab` instances, each of which maintains its
own history, DOM tree and layout state. The :class:`Chrome` class
implements a minimal shim around the tab bar. The :class:`Tab` class
contains the logic for navigation, parsing, styling, layout and
painting, delegating to submodules for networking, DOM parsing,
styling, layout and JavaScript execution.

The code here is adapted from the original monolithic browser. It has
been adjusted to import functionality from the ``project.networking``,
``project.dom``, ``project.css``, ``project.layout`` and
``project.javascript`` modules. At runtime the :class:`Browser` class
injects itself into the layout module to enable hit testing via
``Browser._register_widget_box`` without creating a circular import.

To run the browser from the command line, execute ``python -m
project.browser [URL]`` or run the module directly. If a URL is
provided it will be loaded in the first tab on startup.
"""

from __future__ import annotations

import sys
import urllib.parse
import tkinter
import tkinter.font
import ssl
import time
import email.utils
from typing import Any, Dict, List, Optional

from .networking import URL, COOKIE_JAR
from .dom import Text, Element, HTMLParser, tree_to_list
from .css import (
    CSSParser,
    cascade_priority,
    DEFAULT_STYLE_SHEET,
    INHERITED_PROPERTIES,
    style,
)
from .layout import (
    DocumentLayout,
    Rect,
    DrawText,
    DrawRect,
    DrawLine,
    DrawOutline,
    paint_tree,
    WIDTH,
    HEIGHT,
    HSTEP,
    VSTEP,
    SCROLL_STEP,
    SCROLLBAR_WIDTH,
    BLOCK_ELEMENTS,
)
from .javascript import JSContext


class Tab:
    """A single browser tab encapsulating navigation history and state."""

    def __init__(self, browser: "Browser", home_url: Optional[URL] = None) -> None:
        # Back reference to the owning Browser
        self.browser: Browser = browser
        # History stack: each entry is a dict with keys url/method/body
        self.history: List[Dict[str, Any]] = []
        self.history_index: int = -1
        # DOM and layout state
        self.nodes: Any = None
        self.document: Optional[DocumentLayout] = None
        self.display_list: List[Any] = []
        self.scroll: int = 0
        self.doc_height: int = HEIGHT
        self.title: str = "New Tab"
        # Focused input element in this tab
        self.focus: Optional[Element] = None
        # Current page URL
        self.url: Optional[URL] = None
        # JavaScript context for this tab (None if JS disabled)
        self.js: Optional[JSContext] = None
        # Keep track of already loaded external scripts and styles
        self.loaded_scripts: set[str] = set()
        self.loaded_styles: Dict[object, List] = {}
        self.extra_style_rules: List[tuple[object, Dict[str, str]]] = []
        # Content Security Policy and referrer policy
        self.allowed_origins: Optional[set[str]] = None
        self.referrer_policy: Optional[str] = None
        # Certificate error state for the last load
        self.cert_error: bool = False
        if home_url is not None:
            self.navigate(home_url)

    # Navigation and history management
    def navigate(self, url: URL, method: str = "GET", body: Optional[str] = None) -> None:
        """Navigate to a new URL, recording history and performing the load."""
        # Trim forward history if navigating after going back
        if self.history_index + 1 < len(self.history):
            self.history = self.history[: self.history_index + 1]
        self.history.append({"url": url, "method": method, "body": body})
        self.history_index += 1
        # Perform the load with POST body if method is POST
        self.load(url, payload=(body if method == "POST" else None))

    def go_back(self) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_history_entry()

    def go_forward(self) -> None:
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self._restore_history_entry()

    def reload(self) -> None:
        if 0 <= self.history_index < len(self.history):
            entry = self.history[self.history_index]
            # As per spec, do not re‑POST on reload; always reload via GET
            self.load(entry["url"], payload=None)

    def _restore_history_entry(self) -> None:
        entry = self.history[self.history_index]
        # Do a GET load when restoring from history
        self.load(entry["url"], payload=None)

    def load(self, url: URL, payload: Optional[str] = None) -> None:
        """Load the given URL with optional POST payload, update DOM and layout."""
        # Determine Referer header based on referrer policy of previous page
        referrer: Optional[str] = None
        if self.history_index > 0 and self.history_index - 1 < len(self.history):
            prev = self.history[self.history_index - 1]
            prev_url = prev.get("url")
            if isinstance(prev_url, URL):
                if self.referrer_policy == "no-referrer":
                    referrer = None
                elif self.referrer_policy == "same-origin":
                    if prev_url.origin() == url.origin():
                        referrer = str(prev_url)
                else:
                    referrer = str(prev_url)
        # Reset certificate error flag
        self.cert_error = False
        try:
            self.browser.set_status("Loading…")
            # Perform network request, capturing headers and body
            headers, body = url.request(referrer=referrer, payload=payload)
            self.browser.set_status("")
        except ssl.SSLError:
            # SSL certificate error
            self.cert_error = True
            self.browser.set_status("⚠ Certificate error")
            try:
                self.browser.update_padlock()
            except Exception:
                pass
            return
        except Exception as ex:
            self.browser.set_status(f"Network error: {ex}")
            return
        # Update current URL
        self.url = url
        # Parse Content-Security-Policy for allowed origins
        self.allowed_origins = None
        csp: Optional[str] = None
        for k, v in (headers or {}).items():
            if k.lower() == "content-security-policy":
                csp = v
                break
        if csp and "default-src" in csp:
            parts = csp.split()
            try:
                idx = parts.index("default-src")
                allowed: set[str] = set()
                for item in parts[idx + 1 :]:
                    item = item.strip().rstrip(";")
                    if item:
                        allowed.add(item)
                self.allowed_origins = allowed if allowed else None
            except ValueError:
                self.allowed_origins = None
        else:
            self.allowed_origins = None
        # Parse Referrer-Policy header
        rp: Optional[str] = None
        for k, v in (headers or {}).items():
            if k.lower() == "referrer-policy":
                rp = v
                break
        self.referrer_policy = rp.strip().lower() if rp else None
        # Parse HTML document
        self.nodes = HTMLParser(body).parse()
        self.title = self._extract_title() or f"{url.host}"
        # Initialize JavaScript context if DukPy is available
        if JSContext is not None:
            try:
                self.js = JSContext(self)
            except Exception:
                self.js = None
        else:
            self.js = None
        # Reset loaded scripts/styles caches
        self.loaded_scripts = set()
        self.loaded_styles = {}
        self.extra_style_rules = []
        # Scan DOM for external scripts and styles before styling/layout
        self.process_scripts_and_styles()
        # Apply styles and layout
        self.apply_styles_and_render()
        # Update JS ID variables after layout
        if self.js:
            try:
                self.js.update_ids()
            except Exception:
                pass
        # Update address bar and UI if this is the active tab
        if self is self.browser.current_tab():
            try:
                self.browser.address.delete(0, "end")
                self.browser.address.insert(0, str(url))
            except Exception:
                pass
            try:
                self.browser.update_padlock()
            except Exception:
                pass
            self.browser.draw()
            self.browser.refresh_tab_strip()

    def render(self) -> None:
        """Recompute layout and display list for the current DOM."""
        Browser._clear_widget_boxes()
        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)
        # Document height for scrollbar calculations
        self.doc_height = self.document.height
        # Ensure scroll value is within range
        self.scroll = min(self.scroll, max(0, self.doc_height - HEIGHT))

    def _extract_title(self) -> Optional[str]:
        """Extract the <title> text from the DOM, if present."""
        def walk(n: Any) -> Optional[str]:
            if isinstance(n, Element) and n.tag == "title":
                buf: List[str] = []
                def collect(t: Any) -> None:
                    if isinstance(t, Text):
                        buf.append(t.text.strip())
                    for c in getattr(t, "children", []):
                        collect(c)
                collect(n)
                return " ".join(x for x in buf if x)
            for c in getattr(n, "children", []):
                r = walk(c)
                if r:
                    return r
            return None
        return walk(self.nodes) if self.nodes else None

    # Event handling and interactions
    def click(self, x: float, y: float) -> None:
        """Handle a click at canvas coordinates (x, y)."""
        doc_y = y + self.scroll
        elt = Browser._hit_widget(x, doc_y)
        # Blur any previously focused input
        self.blur()
        if elt is not None:
            # Dispatch click event to JS; honour preventDefault
            prevent = False
            if self.js:
                try:
                    prevent = self.js.dispatch_event("click", elt)
                except Exception:
                    prevent = False
            if prevent:
                self.apply_styles_and_render()
                return
            # Anchor links
            if isinstance(elt, Element) and elt.tag == "a" and "href" in elt.attributes:
                try:
                    new_url = self.url.resolve(elt.attributes["href"]) if self.url else URL(elt.attributes["href"])
                except Exception:
                    new_url = None
                if new_url:
                    self.navigate(new_url)
                    return
            # Input elements: checkbox or text
            if isinstance(elt, Element) and elt.tag == "input":
                itype = elt.attributes.get("type", "text").lower()
                if itype == "checkbox":
                    # Toggle checked state
                    if ("checked" in elt.attributes) or (elt.attributes.get("_checked_state") == "true"):
                        if "checked" in elt.attributes:
                            del elt.attributes["checked"]
                        elt.attributes["_checked_state"] = "false"
                    else:
                        elt.attributes["_checked_state"] = "true"
                    self.apply_styles_and_render()
                    return
                # Text input: clear value and focus
                elt.attributes["value"] = ""
                self.focus = elt
                elt.is_focused = True
                self.apply_styles_and_render()
                return
            # Button click submits enclosing form
            if isinstance(elt, Element) and elt.tag == "button":
                form = elt.parent
                while form and not (isinstance(form, Element) and form.tag == "form"):
                    form = getattr(form, "parent", None)
                if form:
                    self.submit_form(form)
                    return
        # Default: re‑render page without action
        self.apply_styles_and_render()

    def keypress(self, char: str) -> None:
        """Handle a character key press on a focused input element."""
        # If nothing is focused or focus isn't an <input>, ignore
        if not self.focus or not (isinstance(self.focus, Element) and self.focus.tag == "input"):
            return
        # Let JavaScript handle keydown; if default prevented, skip
        prevent = False
        if self.js:
            try:
                prevent = self.js.dispatch_event("keydown", self.focus)
            except Exception:
                prevent = False
        if prevent:
            self.apply_styles_and_render()
            return
        # Input type determines behaviour
        node = self.focus
        itype = node.attributes.get("type", "text").lower()
        # Checkboxes do not accept keystrokes
        if itype == "checkbox":
            return
        # Backspace deletes last character
        if char == "\b":
            raw = node.attributes.get("value", "")
            node.attributes["value"] = raw[:-1]
            self.apply_styles_and_render()
            return
        # Enter submits enclosing form
        if char in ("\r", "\n"):
            form = node.parent
            while form and not (isinstance(form, Element) and form.tag == "form"):
                form = getattr(form, "parent", None)
            if form:
                self.submit_form(form)
            return
        # Append typed character to input value
        node.attributes["value"] = node.attributes.get("value", "") + char
        self.apply_styles_and_render()

    def allowed_request(self, url: URL) -> bool:
        """Check whether a request is allowed under the current CSP."""
        if self.allowed_origins is None:
            return True
        try:
            origin = url.origin()
        except Exception:
            return False
        return origin in self.allowed_origins

    def process_scripts_and_styles(self) -> None:
        """Scan the DOM for <script> and <link rel="stylesheet"> tags."""
        if not self.nodes:
            return
        new_loaded_styles: Dict[object, List] = {}
        # Traverse all nodes in preorder
        for node in tree_to_list(self.nodes, []):
            if isinstance(node, Element):
                # <script src="…"> external scripts
                if node.tag == "script" and "src" in node.attributes:
                    src = node.attributes["src"]
                    if src not in self.loaded_scripts and self.js:
                        # Resolve URL; skip if invalid or blocked by CSP
                        try:
                            script_url = self.url.resolve(src) if self.url else URL(src)
                        except Exception:
                            script_url = None
                        if script_url and not self.allowed_request(script_url):
                            self.loaded_scripts.add(src)
                        elif script_url:
                            try:
                                ref = str(self.url) if self.url else None
                                origin = self.url.origin() if self.url else None
                                h, body = script_url.request(referrer=ref, payload=None, origin=origin)
                                try:
                                    self.js.run(body) if self.js else None
                                except Exception:
                                    pass
                                self.loaded_scripts.add(src)
                            except Exception:
                                # Network error: mark as loaded to avoid retry
                                self.loaded_scripts.add(src)
                                pass
                # <link rel="stylesheet" href="…"> external stylesheets
                if node.tag == "link" and node.attributes.get("rel", "").casefold() == "stylesheet" and "href" in node.attributes:
                    href = node.attributes["href"]
                    try:
                        css_url = self.url.resolve(href) if self.url else URL(href)
                    except Exception:
                        css_url = None
                    if css_url and not self.allowed_request(css_url):
                        continue
                    if node not in self.loaded_styles:
                        rules: List = []
                        if css_url:
                            try:
                                ref = str(self.url) if self.url else None
                                origin_header = self.url.origin() if self.url else None
                                h, css_body = css_url.request(referrer=ref, payload=None, origin=origin_header)
                                parser = CSSParser(css_body)
                                rules = parser.parse()
                            except Exception:
                                rules = []
                        new_loaded_styles[node] = rules
                    else:
                        new_loaded_styles[node] = self.loaded_styles[node]
        # Update cache and flatten extra rules
        self.loaded_styles = new_loaded_styles
        extra: List[tuple[object, Dict[str, str]]] = []
        for rules in self.loaded_styles.values():
            extra.extend(rules)
        self.extra_style_rules = extra

    def apply_styles_and_render(self) -> None:
        """Apply CSS styles and compute layout/display list."""
        if not self.nodes:
            return
        # Compose style rules from default sheet and external sheets
        rules = list(DEFAULT_STYLE_SHEET) + list(self.extra_style_rules)
        rules.sort(key=cascade_priority)
        style(self.nodes, rules)
        self.render()
        # If this tab is active, redraw the canvas
        if self is self.browser.current_tab():
            try:
                self.browser.draw()
            except Exception:
                pass

    def scrolldown(self, px: int) -> None:
        """Scroll down by px pixels, bounded by document height."""
        self.scroll = min(self.scroll + px, max(0, self.doc_height - HEIGHT))

    def scrollup(self, px: int) -> None:
        """Scroll up by px pixels, bounded by zero."""
        self.scroll = max(0, self.scroll - px)

    def blur(self) -> None:
        """Clear the current focus within this tab and unfocus any input."""
        if self.focus:
            self.focus.is_focused = False
        self.focus = None

    def submit_form(self, form_elt: Element) -> None:
        """Submit an HTML form element by collecting inputs and navigating."""
        # Dispatch submit event to JS; skip if default prevented
        prevent = False
        if self.js:
            try:
                prevent = self.js.dispatch_event("submit", form_elt)
            except Exception:
                prevent = False
        if prevent:
            self.apply_styles_and_render()
            return
        # Collect all input elements with a name
        inputs = [n for n in tree_to_list(form_elt, []) if isinstance(n, Element) and n.tag == "input" and "name" in n.attributes]
        parts: List[str] = []
        for inp in inputs:
            itype = inp.attributes.get("type", "text").lower()
            if itype == "checkbox":
                checked = ("checked" in inp.attributes) or (inp.attributes.get("_checked_state") == "true")
                if not checked:
                    continue
                name = urllib.parse.quote(inp.attributes["name"])
                value = urllib.parse.quote(inp.attributes.get("value", "on"))
                parts.append(f"{name}={value}")
            else:
                name = urllib.parse.quote(inp.attributes["name"])
                value = urllib.parse.quote(inp.attributes.get("value", ""))
                parts.append(f"{name}={value}")
        body = "&".join(parts)
        # Determine action URL; default to current URL
        action = form_elt.attributes.get("action", "")
        try:
            url = self.url.resolve(action) if self.url else URL(action)
        except Exception:
            return
        # Navigate with POST
        self.navigate(url, method="POST", body=body)


class Chrome:
    """Simple tab strip shim (mostly unused in the modular version)."""
    def __init__(self, browser: "Browser") -> None:
        self.browser = browser
        self.focus: Optional[str] = None
        self.bottom: int = 0

    def tab_rect(self, i: int) -> Rect:
        x0 = 6 + i * 140
        return Rect(x0, 2, x0 + 128, 28)

    def draw(self) -> None:
        pass

    def click(self, x: float, y: float) -> None:
        for i in range(len(self.browser.tabs)):
            r = self.tab_rect(i)
            if r.contains_point(x, y):
                self.browser.switch_tab(i)
                return

    def keypress(self, char: str) -> bool:
        if self.focus == "address bar":
            self.browser.address.insert("end", char)
            return True
        return False

    def enter(self) -> None:
        self.browser.go_address()

    def blur(self) -> None:
        self.focus = None


class Browser:
    """Main browser window managing tabs, UI and event dispatch."""
    # Class‑level list of widget hit boxes: (Rect, Element)
    _widget_boxes: List[tuple[Rect, Element]] = []

    @classmethod
    def _register_widget_box(cls, element: Element, rect_tuple: tuple[float, float, float, float]) -> None:
        x1, y1, x2, y2 = rect_tuple
        cls._widget_boxes.append((Rect(x1, y1, x2, y2), element))

    @classmethod
    def _clear_widget_boxes(cls) -> None:
        cls._widget_boxes = []

    @classmethod
    def _hit_widget(cls, x: float, y: float) -> Optional[Element]:
        for r, elt in reversed(cls._widget_boxes):
            if r.contains_point(x, y):
                return elt
        return None

    def __init__(self) -> None:
        # Create main window
        self.window = tkinter.Tk()
        self.chrome_ctl = Chrome(self)
        # Tab bar frame
        self.tabbar = tkinter.Frame(self.window, bg="#e6e6e6")
        self.tabbar.pack(fill="x")
        # List of tabs and active index
        self.tabs: List[Tab] = []
        self.active_tab_index: int = 0
        # Chrome/address bar
        self.chrome = tkinter.Frame(self.window)
        self.back_btn = tkinter.Button(self.chrome, text="◀", width=2, command=self.go_back)
        self.fwd_btn = tkinter.Button(self.chrome, text="▶", width=2, command=self.go_forward)
        self.reload_btn = tkinter.Button(self.chrome, text="⟳", width=2, command=self.reload)
        self.padlock = tkinter.Label(self.chrome, text="", width=2)
        self.address = tkinter.Entry(self.chrome, width=60)
        self.go_btn = tkinter.Button(self.chrome, text="Go", command=self.go_address)
        # Pack chrome widgets
        self.back_btn.pack(side="left")
        self.fwd_btn.pack(side="left")
        self.reload_btn.pack(side="left")
        self.padlock.pack(side="left")
        self.address.pack(side="left", fill="x", expand=True, padx=4)
        self.go_btn.pack(side="left")
        self.chrome.pack(fill="x")
        # Canvas for page rendering
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT, background="white", highlightthickness=0)
        self.canvas.pack()
        # Status bar
        self.status = tkinter.Label(self.window, text="", anchor="w")
        self.status.pack(fill="x")
        # Scrollbar state
        self._dragging_scroll: bool = False
        self._drag_offset: int = 0
        self.scrollbar_thumb: Optional[tuple[int, int, int, int]] = None
        self._scroll_velocity: float = 0.0
        self._scroll_animating: bool = False
        # Event bindings
        self.window.bind("<Return>", lambda e: self.handle_enter())
        self.window.bind("<Down>", lambda e: self.scroll_active(+SCROLL_STEP))
        self.window.bind("<Up>", lambda e: self.scroll_active(-SCROLL_STEP))
        self.window.bind("<Prior>", lambda e: self.scroll_active(-int(HEIGHT * 0.9)))
        self.window.bind("<Next>", lambda e: self.scroll_active(+int(HEIGHT * 0.9)))
        self.window.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Button-4>", self.on_wheel_linux)
        self.canvas.bind("<Button-5>", self.on_wheel_linux)
        self.canvas.bind("<Button-1>", self.handle_click)
        self.canvas.bind("<B1-Motion>", self.handle_drag)
        self.canvas.bind("<ButtonRelease-1>", self.handle_release)
        self.window.bind("<Key>", self.handle_key)
        # Keyboard accelerators
        self._bind_accels()
        # Create first tab with a default home page
        self.new_tab(URL("http://www.textfiles.com/"))
        # Inject Browser into layout for hit testing
        from . import layout as _layout_module  # local import to avoid circular dependency at import time
        _layout_module.Browser = Browser

    # UI update methods
    def update_padlock(self) -> None:
        """Update the padlock icon based on the current tab's security state."""
        try:
            tab = self.current_tab()
        except Exception:
            return
        if getattr(tab, "url", None) and isinstance(tab.url, URL) and tab.url.scheme == "https" and not getattr(tab, "cert_error", False):
            self.padlock.config(text="\N{lock}")
        else:
            self.padlock.config(text="")

    # Accelerator key bindings
    def _bind_accels(self) -> None:
        def bind_combo(key: str, handler) -> None:
            self.window.bind(f"<Control-{key}>", handler)
            self.window.bind(f"<Command-{key}>", handler)
        # New tab: Ctrl/Cmd+T opens example.org
        bind_combo("t", lambda e: self.new_tab(URL("https://example.org/")))
        # Close tab: Ctrl/Cmd+W
        bind_combo("w", lambda e: self.close_tab(self.active_tab_index))
        # Focus address bar: Ctrl/Cmd+L
        bind_combo("l", lambda e: (self.address.focus_set(), self.address.selection_range(0, "end")))
        # Next/prev tab bindings
        def next_tab(e=None):
            if self.tabs:
                self.switch_tab((self.active_tab_index + 1) % len(self.tabs))
        def prev_tab(e=None):
            if self.tabs:
                self.switch_tab((self.active_tab_index - 1) % len(self.tabs))
        self.window.bind("<Control-Tab>", lambda e: next_tab())
        self.window.bind("<Control-Shift-Tab>", lambda e: prev_tab())
        self.window.bind("<Command-Right>", lambda e: next_tab())
        self.window.bind("<Command-Left>", lambda e: prev_tab())
        # Copy page text to clipboard: Ctrl/Cmd+C
        def copy_page(e=None):
            try:
                text = self._gather_text(self.current_tab().nodes)
                self.window.clipboard_clear()
                self.window.clipboard_append(text)
            except Exception:
                pass
            return "break"
        self.window.bind("<Control-c>", lambda e: copy_page())
        self.window.bind("<Command-c>", lambda e: copy_page())

    # Tab management
    def current_tab(self) -> Tab:
        return self.tabs[self.active_tab_index]

    def _gather_text(self, node: Any) -> str:
        """Recursively collect visible text from the DOM tree."""
        out = ""
        if isinstance(node, Text):
            out += node.text
        elif isinstance(node, Element):
            # Determine if this element is block level to insert line breaks
            is_block = node.tag in BLOCK_ELEMENTS or node.tag in ("br",)
            for child in node.children:
                out += self._gather_text(child)
            if is_block:
                out += "\n"
        else:
            for child in getattr(node, "children", []):
                out += self._gather_text(child)
        return out

    def new_tab(self, url: URL) -> None:
        tab = Tab(self)
        self.tabs.append(tab)
        self.active_tab_index = len(self.tabs) - 1
        self.refresh_tab_strip()
        if url:
            tab.navigate(url)
        self.draw()
        try:
            self.canvas.focus_set()
        except Exception:
            pass

    def switch_tab(self, idx: int) -> None:
        if 0 <= idx < len(self.tabs):
            self.active_tab_index = idx
            tab = self.current_tab()
            if 0 <= tab.history_index < len(tab.history):
                url = tab.history[tab.history_index]["url"]
                try:
                    self.address.delete(0, "end")
                    self.address.insert(0, str(url))
                except Exception:
                    pass
            self.refresh_tab_strip()
            self.draw()

    def close_tab(self, idx: int) -> None:
        if len(self.tabs) <= 1:
            try:
                self.window.quit()
            finally:
                self.window.destroy()
            return
        del self.tabs[idx]
        if self.active_tab_index >= len(self.tabs):
            self.active_tab_index = len(self.tabs) - 1
        self.refresh_tab_strip()
        self.draw()

    def refresh_tab_strip(self) -> None:
        for w in self.tabbar.winfo_children():
            w.destroy()
        for i, t in enumerate(self.tabs):
            cell = tkinter.Frame(self.tabbar, bd=0, relief="flat", bg="#e6e6e6")
            title = t.title or "New Tab"
            title_txt = title[:24] + ("…" if len(title) > 24 else "")
            b = tkinter.Button(
                cell,
                text=title_txt,
                command=lambda j=i: self.switch_tab(j),
                relief="sunken" if i == self.active_tab_index else "raised",
            )
            b.pack(side="left", padx=(2, 2), pady=2)
            xbtn = tkinter.Button(cell, text="×", width=2, command=lambda j=i: self.close_tab(j))
            xbtn.pack(side="left", padx=(2, 4), pady=2)
            cell.pack(side="left")
        plus = tkinter.Button(self.tabbar, text="+", width=3, command=lambda: self.new_tab(URL("https://example.org/")))
        plus.pack(side="left", padx=4, pady=2)

    # Event handlers
    def handle_click(self, e: Any) -> None:
        # Check if click was on scrollbar track
        track_left = WIDTH - SCROLLBAR_WIDTH
        if e.x >= track_left:
            tab = self.current_tab()
            if tab.doc_height > HEIGHT and self.scrollbar_thumb:
                x1, y1, x2, y2 = self.scrollbar_thumb
                if y1 <= e.y <= y2:
                    self._dragging_scroll = True
                    self._drag_offset = e.y - y1
                else:
                    thumb_h = y2 - y1
                    new_y = max(0, min(e.y - thumb_h // 2, HEIGHT - thumb_h))
                    ratio = new_y / (HEIGHT - thumb_h)
                    tab.scroll = int(ratio * (tab.doc_height - HEIGHT))
                    self.draw()
            return
        # Clear selection and blur address bar
        try:
            self.address.selection_clear()
            self.address.icursor("end")
        except Exception:
            pass
        self.chrome_ctl.blur()
        self.current_tab().blur()
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        # Delegate click to current tab
        self.current_tab().click(e.x, e.y)
        self.draw()

    def handle_drag(self, e: Any) -> None:
        if not self._dragging_scroll or not self.scrollbar_thumb:
            return
        tab = self.current_tab()
        x1, y1, x2, y2 = self.scrollbar_thumb
        thumb_h = y2 - y1
        new_y = max(0, min(e.y - self._drag_offset, HEIGHT - thumb_h))
        ratio = new_y / (HEIGHT - thumb_h)
        tab.scroll = int(ratio * (tab.doc_height - HEIGHT))
        self.draw()

    def handle_release(self, e: Any) -> None:
        self._dragging_scroll = False

    def handle_key(self, e: Any) -> None:
        widget = self.window.focus_get()
        if widget is self.address:
            self.chrome_ctl.focus = "address bar"
            self.current_tab().blur()
            return
        self.chrome_ctl.focus = None
        if e.char:
            self.current_tab().keypress(e.char)
            self.draw()

    def handle_enter(self) -> None:
        widget = self.window.focus_get()
        if widget is self.address:
            self.go_address()

    # Navigation commands
    def set_status(self, msg: str) -> None:
        self.status.config(text=msg)

    def go_address(self) -> None:
        self.current_tab().blur()
        url_str = self.address.get().strip()
        if not url_str:
            return
        if "://" not in url_str:
            url_str = "https://" + url_str
        try:
            url = URL(url_str)
        except Exception:
            self.set_status(f"Invalid URL: {url_str}")
            return
        self.current_tab().navigate(url)

    def go_back(self) -> None:
        self.current_tab().go_back()

    def go_forward(self) -> None:
        self.current_tab().go_forward()

    def reload(self) -> None:
        self.current_tab().reload()

    # Scrolling
    def scroll_active(self, delta: int) -> None:
        tab = self.current_tab()
        if delta >= 0:
            tab.scrolldown(delta)
        else:
            tab.scrollup(-delta)
        self.draw()

    def on_wheel(self, e: Any) -> None:
        # Normalize wheel delta to pixel scroll
        if sys.platform == "darwin":
            step = -float(e.delta) * 4.0
        else:
            step = -int(e.delta / 120) * 40
        self._enqueue_scroll(step)

    def on_wheel_linux(self, e: Any) -> None:
        step = -40 if e.num == 4 else +40
        self._enqueue_scroll(step)

    def _enqueue_scroll(self, step: float) -> None:
        self._scroll_velocity += step
        if not self._scroll_animating:
            self._scroll_animating = True
            self._scroll_tick()

    def _scroll_tick(self) -> None:
        v = self._scroll_velocity
        if abs(v) < 0.5:
            self._scroll_velocity = 0.0
            self._scroll_animating = False
            return
        step = int(v)
        if step != 0:
            self.scroll_active(step)
        self._scroll_velocity = v * 0.85
        self.window.after(16, self._scroll_tick)

    # Painting
    def draw(self) -> None:
        tab = self.current_tab()
        self.canvas.delete("all")
        for cmd in tab.display_list:
            cmd.execute(tab.scroll, self.canvas)
        self.draw_scrollbar(tab)

    def draw_scrollbar(self, tab: Tab) -> None:
        track_left = WIDTH - SCROLLBAR_WIDTH
        self.canvas.create_rectangle(track_left, 0, WIDTH, HEIGHT, width=0, fill="#f0f0f0")
        if tab.doc_height <= HEIGHT:
            self.scrollbar_thumb = None
            return
        ratio = HEIGHT / tab.doc_height
        thumb_h = max(30, int(HEIGHT * ratio))
        max_scroll = tab.doc_height - HEIGHT
        thumb_y = int((tab.scroll / max_scroll) * (HEIGHT - thumb_h))
        self.scrollbar_thumb = (track_left, thumb_y, WIDTH, thumb_y + thumb_h)
        self.canvas.create_rectangle(*self.scrollbar_thumb, width=1, outline="#bbb", fill="#ccc")


def main() -> None:
    """Entry point for running the browser via ``python -m project.browser``."""
    app = Browser()
    # If a URL argument is provided, load it in the first tab
    if len(sys.argv) >= 2:
        try:
            url = URL(sys.argv[1])
        except Exception:
            app.set_status(f"Invalid URL: {sys.argv[1]}")
        else:
            app.current_tab().navigate(url)
    # Enter Tkinter main loop
    tkinter.mainloop()


if __name__ == "__main__":
    main()