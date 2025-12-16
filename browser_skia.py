import sys
import ctypes
import math
import sdl2
import skia
import tools

from browser import WIDTH, HEIGHT, VSTEP, SCROLL_STEP
from browser import style, cascade_priority
from browser import DrawText, DrawLine, DrawOutline, DrawRect
from browser import Text, Element, BlockLayout, InputLayout
from browser import Browser, LineLayout, TextLayout, DocumentLayout, Chrome
from browser import DEFAULT_STYLE_SHEET, INPUT_WIDTH_PX, URL, Tab

FONTS = {}

def get_font(size, weight, style):
    key = (weight, style)
    if key not in FONTS:
        if weight == "bold":
            skia_weight = skia.FontStyle.kBold_Weight
        else:
            skia_weight = skia.FontStyle.kNormal_Weight
        if style == "italic":
            skia_style = skia.FontStyle.kItalic_Slant
        else:
            skia_style = skia.FontStyle.kUpright_Slant
        skia_width = skia.FontStyle.kNormal_Width
        style_info = \
            skia.FontStyle(skia_weight, skia_width, skia_style)
        font = skia.Typeface('Arial', style_info)
        FONTS[key] = font
    return skia.Font(FONTS[key], size)

NAMED_COLORS = {
    "black": "#000000",
    "gray":  "#808080",
    "white": "#ffffff",
    "red":   "#ff0000",
    "green": "#00ff00",
    "blue":  "#0000ff",
    "lightblue": "#add8e6",
    "lightgreen": "#90ee90",
    "orange": "#ffa500",
    "orangered": "#ff4500",
}

def parse_color(color):
    if color.startswith("#") and len(color) == 7:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return skia.Color(r, g, b)
    elif color.startswith("#") and len(color) == 9:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        a = int(color[7:9], 16)
        return skia.Color(r, g, b, a)
    elif color in NAMED_COLORS:
        return parse_color(NAMED_COLORS[color])
    else:
        return skia.ColorBLACK

def parse_blend_mode(blend_mode_str):
    if blend_mode_str == "multiply":
        return skia.BlendMode.kMultiply
    elif blend_mode_str == "difference":
        return skia.BlendMode.kDifference
    elif blend_mode_str == "destination-in":
        return skia.BlendMode.kDstIn
    elif blend_mode_str == "source-over":
        return skia.BlendMode.kSrcOver
    else:
        return skia.BlendMode.kSrcOver

def linespace(font):
    metrics = font.getMetrics()
    return metrics.fDescent - metrics.fAscent

class Blend:
    def __init__(self, opacity, blend_mode, children):
        self.opacity = opacity
        self.blend_mode = blend_mode
        self.should_save = self.blend_mode or self.opacity < 1

        self.children = children
        self.rect = skia.Rect.MakeEmpty()
        for cmd in self.children:
            self.rect.join(cmd.rect)

    def execute(self, canvas):
        paint = skia.Paint(
            Alphaf=self.opacity,
            BlendMode=parse_blend_mode(self.blend_mode),
        )
        if self.should_save:
            canvas.saveLayer(None, paint)
        for cmd in self.children:
            cmd.execute(canvas)
        if self.should_save:
            canvas.restore()

@tools.patch(DrawRect)
class DrawRect:
    def __init__(self, rect, color):
        self.rect = rect
        self.color = color

    def execute(self, canvas):
        paint = skia.Paint(
            Color=parse_color(self.color),
        )
        canvas.drawRect(self.rect, paint)

    @tools.js_hide
    def __repr__(self):
        return "DrawRect(top={} left={} bottom={} right={} color={})".format(
            self.rect.top(), self.rect.left(), self.rect.bottom(),
            self.rect.right(), self.color)

@tools.patch(DrawText)
class DrawText:
    def __init__(self, x, y, text, font, color):
        self.x = x
        self.y = y
        self.text = text
        self.color = color

        # Unwrap our stable-font wrapper from browser.py
        # (browser.get_font returns _SkiaFont with .skia_font)
        if hasattr(font, "skia_font"):
            self.font = font.skia_font
        else:
            self.font = font  # might already be skia.Font

        # Build text blob using a real skia.Font
        self.blob = skia.TextBlob.MakeFromText(self.text, self.font, skia.TextEncoding.kUTF8)
        self.rect = self.blob.bounds().makeOffset(self.x, self.y)

    def execute(self, canvas):
        paint = skia.Paint(AntiAlias=True, Color=parse_color(self.color))
        canvas.drawTextBlob(self.blob, self.x, self.y, paint)


@tools.patch(DrawOutline)
class DrawOutline:
    def __init__(self, rect, color, thickness):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        paint = skia.Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=skia.Paint.kStroke_Style,
        )
        canvas.drawRect(self.rect, paint)

@tools.patch(DrawLine)
class DrawLine:
    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = skia.Rect.MakeLTRB(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        path = skia.Path().moveTo(
            self.rect.left(), self.rect.top()) \
                .lineTo(self.rect.right(),
                    self.rect.bottom())
        paint = skia.Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=skia.Paint.kStroke_Style,
        )
        canvas.drawPath(path, paint)

class DrawRRect:
    def __init__(self, rect, radius, color):
        self.rect = rect
        self.rrect = skia.RRect.MakeRectXY(rect, radius, radius)
        self.color = color

    def execute(self, canvas):
        paint = skia.Paint(
            Color=parse_color(self.color),
        )
        canvas.drawRRect(self.rrect, paint)

def paint_tree(layout_object, display_list):
    """Depth-first paint traversal.

    If a node paints (should_paint True), we collect its subtree commands into a
    local list so that visual effects (opacity/overflow) can wrap the subtree.

    If a node does *not* paint, its children must paint directly into the
    parent's list (display_list), otherwise the subtree gets dropped and you see
    a white page.
    """
    should = getattr(layout_object, "should_paint", None)
    paints = should() if callable(should) else (not isinstance(layout_object, DocumentLayout))

    if paints:
        cmds = layout_object.paint()
        for child in layout_object.children:
            paint_tree(child, cmds)
        cmds = layout_object.paint_effects(cmds)
        display_list.extend(cmds)
    else:
        for child in getattr(layout_object, "children", []):
            paint_tree(child, display_list)

@tools.patch(BlockLayout)
class BlockLayout:
    # IMPORTANT: Do NOT override word()/input() here.
    # Your browser.py generates inline drawing into self.display_list.
    # If you ignore display_list, the page renders blank.

    def self_rect(self):
        return skia.Rect.MakeLTRB(
            self.x, self.y,
            self.x + self.width, self.y + self.height)

    def paint(self):
        cmds = [] 

        # Background (with optional border-radius)
        bgcolor = self.node.style.get("background-color", "transparent")
        if bgcolor != "transparent":
            try:
                radius = float(self.node.style.get("border-radius", "0px")[:-2])
            except Exception:
                radius = 0.0
            if radius:
                cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))
            else:
                cmds.append(DrawRect(self.self_rect(), bgcolor))

        # Match book behavior for <pre>
        if isinstance(self.node, Element) and self.node.tag == "pre":
            cmds.append(DrawRect(self.self_rect(), "gray"))

        # The REAL content: inline display list produced by browser.py
        for item in getattr(self, "display_list", []):
            tag = item[0] if isinstance(item, tuple) and item else None

            if tag == "text_abs":
                _, (x, y), word, font, color = item
                cmds.append(DrawText(x, y, word, font, color))

            elif tag == "rect":
                _, (x1, y1, x2, y2), color = item
                rect = skia.Rect.MakeLTRB(x1, y1, x2, y2)
                cmds.append(DrawRect(rect, color))

            elif tag == "outline":
                _, (x1, y1, x2, y2), color, th = item
                rect = skia.Rect.MakeLTRB(x1, y1, x2, y2)
                cmds.append(DrawOutline(rect, color, th))

            elif tag == "line":
                _, (x1, y1, x2, y2, color, th) = item
                cmds.append(DrawLine(x1, y1, x2, y2, color, th))

            # Older format fallback: (x, y, word, font, color)
            elif tag is None and len(item) == 5:
                x, y, word, font, color = item
                cmds.append(DrawText(x, y, word, font, color))

        return cmds

    def paint_effects(self, cmds):
        return paint_visual_effects(self.node, cmds, self.self_rect())

@tools.patch(LineLayout)
class LineLayout:
    def layout(self):
        self.width = self.parent.width
        self.x = self.parent.x

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        for word in self.children:
            word.layout()

        if not self.children:
            self.height = 0
            return

        max_ascent = max([-word.font.getMetrics().fAscent 
                          for word in self.children])
        baseline = self.y + 1.25 * max_ascent
        for word in self.children:
            word.y = baseline + word.font.getMetrics().fAscent
        max_descent = max([word.font.getMetrics().fDescent
                           for word in self.children])
        self.height = 1.25 * (max_ascent + max_descent)

    def paint(self):
        return []
    
    def paint_effects(self, cmds):
        return cmds

@tools.patch(TextLayout)
class TextLayout:
    def layout(self):
        weight = self.node.style["font-weight"]
        style = self.node.style["font-style"]
        size = float(self.node.style["font-size"][:-2]) * 0.75
        self.font = get_font(size, weight, style)

        # Do not set self.y!!!
        self.width = self.font.measureText(self.word)

        if self.previous:
            space = self.previous.font.measureText(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = linespace(self.font)

    def paint(self):
        cmds = []
        metrics = self.font.getMetrics()
        baseline_adjust = -metrics.fAscent  # ascent is negative
        color = self.node.style["color"]
        cmds.append(
            DrawText(self.x, self.y, self.word, self.font, color))
        return cmds

    def paint_effects(self, cmds):
        return cmds

@tools.patch(InputLayout)
class InputLayout:
    def layout(self):
        weight = self.node.style["font-weight"]
        style = self.node.style["font-style"]
        size = float(self.node.style["font-size"][:-2]) * 0.75
        self.font = get_font(size, weight, style)

        self.width = INPUT_WIDTH_PX
        self.height = linespace(self.font)

        if self.previous:
            space = self.previous.font.measureText(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

    def self_rect(self):
        return skia.Rect.MakeLTRB(
            self.x, self.y, self.x + self.width,
            self.y + self.height)

    def should_paint(self):
        return True

    def paint(self):
        cmds = []

        bgcolor = self.node.style.get("background-color",
                                 "transparent")
        if bgcolor != "transparent":
            radius = float(self.node.style.get("border-radius", "0px")[:-2])
            cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))

        if self.node.tag == "input":
            text = self.node.attributes.get("value", "")
        elif self.node.tag == "button":
            if len(self.node.children) == 1 and \
               isinstance(self.node.children[0], Text):
                text = self.node.children[0].text
            else:
                print("Ignoring HTML contents inside button")
                text = ""

        color = self.node.style["color"]
        cmds.append(DrawText(self.x, self.y,
                             text, self.font, color))

        if self.node.is_focused:
            cx = self.x + self.font.measureText(text)
            cmds.append(DrawLine(
                cx, self.y, cx, self.y + self.height, "black", 1))

        return cmds

    def paint_effects(self, cmds):
        return paint_visual_effects(self.node, cmds, self.self_rect())

def paint_visual_effects(node, cmds, rect):
    opacity = float(node.style.get("opacity", "1.0"))
    blend_mode = node.style.get("mix-blend-mode")

    if node.style.get("overflow", "visible") == "clip":
        border_radius = float(node.style.get(
            "border-radius", "0px")[:-2])
        if not blend_mode:
            blend_mode = "source-over"
        cmds.append(Blend(1.0, "destination-in", [
            DrawRRect(rect, border_radius, "white")
        ]))

    return [Blend(opacity, blend_mode, cmds)]

@tools.patch(DocumentLayout)
class DocumentLayout:
    def paint(self):
        return []

    def paint_effects(self, cmds):
        return cmds

@tools.patch(Tab)
class Tab:
    def render(self):
        rules = DEFAULT_STYLE_SHEET + self.extra_style_rules
        rules.sort(key=cascade_priority)
        style(self.nodes, rules)
        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)

    def raster(self, canvas):
        for cmd in self.display_list:
            cmd.execute(canvas)


    def clamp_scroll(self):
        # In the Skia UI, only the content area is scrollable (below chrome).
        viewport = HEIGHT - self.browser.chrome.bottom
        self.scroll = max(0, min(self.scroll, max(0, self.doc_height - viewport)))
    @tools.delete
    def draw(self, canvas, offset): pass

@tools.patch(Chrome)
class Chrome:
    def __init__(self, browser):
        self.browser = browser
        self.focus = None
        self.address_bar = ""

        self.font = get_font(20, "normal", "roman")
        self.font_height = linespace(self.font)

        self.padding = 5
        self.tabbar_top = 0
        self.tabbar_bottom = self.font_height + 2*self.padding

        plus_width = self.font.measureText("+") + 2*self.padding
        self.newtab_rect = skia.Rect.MakeLTRB(
           self.padding, self.padding,
           self.padding + plus_width,
           self.padding + self.font_height)

        self.urlbar_top = self.tabbar_bottom
        self.urlbar_bottom = self.urlbar_top + \
            self.font_height + 2*self.padding

        back_width = self.font.measureText("<") + 2*self.padding
        self.back_rect = skia.Rect.MakeLTRB(
            self.padding,
            self.urlbar_top + self.padding,
            self.padding + back_width,
            self.urlbar_bottom - self.padding)

        self.address_rect = skia.Rect.MakeLTRB(
            self.back_rect.right() + self.padding,
            self.urlbar_top + self.padding,
            WIDTH - self.padding,
            self.urlbar_bottom - self.padding)

        self.bottom = self.urlbar_bottom

    def _tab_display_title(self, tab):
        """
        Return a truncated title for display on a tab. Long titles are
        abbreviated with an ellipsis to avoid tabs becoming excessively
        wide. A maximum number of characters is enforced to cap the tab
        width. If no title is set on the Tab object, fall back to the
        host name or "New Tab".
        """
        # Prefer the tab's title; if absent, use the URL host
        raw_title = getattr(tab, 'title', None) or getattr(tab, 'url', None)
        if not raw_title:
            return "New Tab"
        if isinstance(raw_title, str):
            title = raw_title
        else:
            # If it's a URL object, convert to host string
            title = getattr(raw_title, 'host', None) or str(raw_title)
        # Truncate to a sensible length for tab display
        max_chars = 20
        if len(title) > max_chars:
            return title[:max_chars - 1] + "…"
        else:
            return title

    def _tab_icon_char(self, tab):
        """
        Determine a one‑character icon for a tab. Use the first
        alphanumeric character of the tab's title, uppercased. If none
        exists, fall back to a default symbol.
        """
        title = getattr(tab, 'title', None) or ''
        if title:
            # Find the first alphanumeric character
            for ch in title:
                if ch.isalnum():
                    return ch.upper()
        return '●'

    def _tab_width(self, tab):
        """
        Compute the width of a tab based on its display title, icon, and
        close button. Includes padding between elements. A small extra
        margin is added to improve legibility.
        """
        display_title = self._tab_display_title(tab)
        icon_char = self._tab_icon_char(tab)
        # Measure individual components
        title_width = self.font.measureText(display_title)
        icon_width = self.font.measureText(icon_char)
        close_width = self.font.measureText("×")
        # Internal spacing between icon, title and close button
        inter_pad = self.padding
        # Outer padding at left and right edges
        outer_pad = self.padding
        # Total width: outer padding + icon + space + title + space + close + outer padding
        width = outer_pad + icon_width + inter_pad + title_width + inter_pad + close_width + outer_pad
        # Impose a minimum width to avoid very narrow tabs
        min_width = self.font.measureText("WWW") + 6 * self.padding
        return max(width, min_width)

    def tab_rect(self, i):
        """
        Compute the bounding rectangle for the i‑th tab. The width of
        each tab is dynamic, based on its content, so this sums the
        widths of all prior tabs to determine the left edge. The y
        coordinates are fixed by the tab bar dimensions.
        """
        # Starting x coordinate after the new tab button
        tabs_start = self.newtab_rect.right() + self.padding
        x_left = tabs_start
        # Sum widths of prior tabs
        for j in range(i):
            x_left += self._tab_width(self.browser.tabs[j])
        # Width of this tab
        width = self._tab_width(self.browser.tabs[i])
        x_right = x_left + width
        return skia.Rect.MakeLTRB(x_left, self.tabbar_top, x_right, self.tabbar_bottom)

    def paint(self):
        cmds = []
        # Draw a horizontal line under the chrome
        cmds.append(DrawLine(
            0, self.bottom, WIDTH,
            self.bottom, "black", 1))

        # Baseline adjustment for font; compute once here
        metrics = self.font.getMetrics()
        baseline_adjust = -metrics.fAscent  # ascent is negative

        # Draw the "+" new tab button
        cmds.append(DrawOutline(self.newtab_rect, "black", 1))
        cmds.append(DrawText(
            self.newtab_rect.left() + self.padding,
            self.newtab_rect.top() + self.padding + baseline_adjust,
            "+", self.font, "black"))

        # Draw each tab with dynamic width, background, icon, title, and close button
        for i, tab in enumerate(self.browser.tabs):
            bounds = self.tab_rect(i)
            # Background fill: lighter for inactive tabs, highlighted for active
            if tab == self.browser.active_tab:
                bg_color = "lightblue"
            else:
                bg_color = "lightgreen"
            cmds.append(DrawRect(bounds, bg_color))
            # Left and right separators
            cmds.append(DrawLine(
                bounds.left(), 0, bounds.left(), bounds.bottom(),
                "black", 1))
            cmds.append(DrawLine(
                bounds.right(), 0, bounds.right(), bounds.bottom(),
                "black", 1))
            # Determine positions for icon, title, and close button
            x = bounds.left() + self.padding
            y = bounds.top() + self.padding + baseline_adjust
            # Draw icon
            icon_char = self._tab_icon_char(tab)
            cmds.append(DrawText(x, y, icon_char, self.font, "black"))
            x += self.font.measureText(icon_char) + self.padding
            # Draw title
            title = self._tab_display_title(tab)
            cmds.append(DrawText(x, y, title, self.font, "black"))
            x += self.font.measureText(title) + self.padding
            # Draw close button
            cmds.append(DrawText(x, y, "×", self.font, "black"))
            # For active tab: draw bottom line across unused area outside tab
            if tab == self.browser.active_tab:
                # Left segment of bottom line
                cmds.append(DrawLine(
                    0, bounds.bottom(), bounds.left(), bounds.bottom(),
                    "black", 1))
                # Right segment of bottom line
                cmds.append(DrawLine(
                    bounds.right(), bounds.bottom(), WIDTH, bounds.bottom(),
                    "black", 1))

        # Back button
        cmds.append(DrawOutline(self.back_rect, "black", 1))
        cmds.append(DrawText(
            self.back_rect.left() + self.padding,
            self.back_rect.top() + baseline_adjust,
            "<", self.font, "black"))

        # Address bar
        cmds.append(DrawOutline(self.address_rect, "black", 1))
        if self.focus == "address bar":
            cmds.append(DrawText(
                self.address_rect.left() + self.padding,
                self.address_rect.top() + baseline_adjust,
                self.address_bar, self.font, "black"))
            w = self.font.measureText(self.address_bar)
            cmds.append(DrawLine(
                self.address_rect.left() + self.padding + w,
                self.address_rect.top(),
                self.address_rect.left() + self.padding + w,
                self.address_rect.bottom(),
                "red", 1))
        else:
            url = str(self.browser.active_tab.url)
            cmds.append(DrawText(
                self.address_rect.left() + self.padding,
                self.address_rect.top() + baseline_adjust,
                url, self.font, "black"))

        return cmds

    def click(self, x, y):
        self.focus = None
        # Click on the new tab button opens a fresh tab
        if self.newtab_rect.contains(x, y):
            self.browser.new_tab(URL("https://browser.engineering/"))
            return
        # Click on the back button navigates history backward
        if self.back_rect.contains(x, y):
            if self.browser.active_tab:
                self.browser.active_tab.go_back()
            # Re‑raster chrome and tab surfaces to reflect navigation
            self.browser.raster_chrome()
            if self.browser.active_tab:
                self.browser.raster_tab()
            self.browser.draw()
            return
        # Click inside address bar focuses it
        if self.address_rect.contains(x, y):
            self.focus = "address bar"
            self.address_bar = ""
            return
        # Otherwise handle clicks on tabs: either activate or close
        # Iterate through each tab and check if the click is within its rect
        tabs = list(self.browser.tabs)
        for i, tab in enumerate(tabs):
            bounds = self.tab_rect(i)
            if bounds.contains(x, y):
                # Determine if click is on the close button region
                close_width = self.font.measureText("×")
                outer_pad = self.padding
                close_left = bounds.right() - (outer_pad + close_width)
                if x >= close_left:
                    # Close this tab
                    self.browser.close_tab(i)
                    return
                else:
                    # Activate this tab
                    self.browser.active_tab = tab
                    self.browser.active_tab_index = i
                    break
        # Re‑raster the current tab (useful when switching)
        if self.browser.active_tab:
            self.browser.raster_tab()

    def enter(self):
        if self.focus == "address bar":
            self.browser.active_tab.navigate(URL(self.address_bar))
            self.focus = None
            self.browser.focus = None

@tools.patch(Browser)
class Browser:
    def __init__(self):
        self.chrome = Chrome(self)

        self.sdl_window = sdl2.SDL_CreateWindow(b"Browser",
            sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
            WIDTH, HEIGHT, sdl2.SDL_WINDOW_SHOWN)
        self.root_surface = skia.Surface.MakeRaster(
            skia.ImageInfo.Make(
            WIDTH, HEIGHT,
            ct=skia.kRGBA_8888_ColorType,
            at=skia.kUnpremul_AlphaType))
        self.chrome_surface = skia.Surface(
            WIDTH, math.ceil(self.chrome.bottom))
        self.tab_surface = None

        self.tabs = []
        self.active_tab_index = 0
        self.active_tab = None
        self.focus = None

    def set_status(self, msg):
        # Lab 11 (SDL/Skia) version: no tkinter widgets.
        self.status = msg
        try:
            sdl2.SDL_SetWindowTitle(
                self.sdl_window,
                f"Browser — {msg}".encode("utf8"),
            )
        except Exception:
            pass


        if sdl2.SDL_BYTEORDER == sdl2.SDL_BIG_ENDIAN:
            self.RED_MASK = 0xff000000
            self.GREEN_MASK = 0x00ff0000
            self.BLUE_MASK = 0x0000ff00
            self.ALPHA_MASK = 0x000000ff
        else:
            self.RED_MASK = 0x000000ff
            self.GREEN_MASK = 0x0000ff00
            self.BLUE_MASK = 0x00ff0000
            self.ALPHA_MASK = 0xff000000

    def handle_click(self, e):
        """
        Handle mouse clicks. Left‑clicks perform normal browser actions (e.g.,
        following links, focusing inputs) while right‑clicks copy the page’s
        visible text to the system clipboard. This mirrors the Tkinter version
        where a right‑click copied all visible text. The SDL_MouseButtonEvent
        passed as ``e`` contains ``button`` (mouse button number), ``x`` and
        ``y`` coordinates. Button 1 is left click; button 3 is right click.
        """
        # Right click copies visible page text to clipboard
        if getattr(e, "button", 1) == 3:
            # Copy all visible text to clipboard and return
            self.copy_to_clipboard()
            return
        # Left click (or other buttons) perform default behavior
        if e.y < self.chrome.bottom:
            # Click within the chrome area
            self.focus = None
            self.chrome.click(e.x, e.y)
            self.raster_chrome()
        else:
            # Click within page content
            if self.focus != "content":
                self.focus = "content"
                self.chrome.blur()
                self.raster_chrome()
            # Adjust for scroll and dispatch click to current tab
            url = self.active_tab.url
            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)
            if self.active_tab.url != url:
                # Navigated to a new page; re‑raster chrome to show new URL
                self.raster_chrome()
            # Always raster tab after clicking
            self.raster_tab()
        # Redraw combined chrome + content
        self.draw()

    def copy_to_clipboard(self):
        """
        Copy all visible text on the current page to the system clipboard.
        This gathers the text from the DOM tree (excluding script and style
        elements) and uses SDL_SetClipboardText to place the text on the
        clipboard. On platforms where SDL_SetClipboardText is unsupported,
        this call safely no‑ops. Press Ctrl+C or right‑click anywhere on the
        page to trigger this function.
        """
        # Collect visible text by traversing the DOM tree
        texts = []
        def traverse(node):
            # Skip script/style tags entirely
            if isinstance(node, Text):
                texts.append(node.text)
            elif isinstance(node, Element):
                tag = node.tag if hasattr(node, "tag") else None
                if tag not in ("script", "style"):
                    for child in getattr(node, "children", []):
                        traverse(child)
        # If there is no active tab or document, do nothing
        if not self.active_tab or not getattr(self.active_tab, "nodes", None):
            return
        traverse(self.active_tab.nodes)
        plain_text = " ".join(texts)
        # Use SDL to put text on the clipboard
        try:
            sdl2.SDL_SetClipboardText(plain_text.encode("utf-8"))
        except Exception:
            # If SDL clipboard API is unavailable, silently ignore
            pass

    def handle_key(self, char):
        if not (0x20 <= ord(char) < 0x7f): return
        if self.chrome.focus:
            self.chrome.keypress(char)
            self.raster_chrome()
            self.draw()
        elif self.focus == "content":
            self.active_tab.keypress(char)
            self.raster_tab()
            self.draw()

    def handle_enter(self):
        if self.chrome.focus:
            self.chrome.enter()
            self.raster_tab()
            self.raster_chrome()
            self.draw()

    def handle_down(self):
        self.active_tab.scrolldown()
        self.draw()

    def handle_up(self):
        """
        Scroll the current page up by one scroll step and redraw. Mirrors
        handle_down() but scrolls in the opposite direction. Without this,
        users cannot move back up a page once they have scrolled down. This
        simply delegates to Tab.scrollup() and then triggers a redraw.
        """
        if self.active_tab:
            # Use the browser-level SCROLL_STEP constant for consistency
            self.active_tab.scrollup()
            self.draw()

    def handle_scroll(self, dy: float):
        """Scroll the active tab by a pixel delta (positive = down)."""
        if not self.active_tab:
            return
        self.active_tab.scroll += dy
        self.active_tab.clamp_scroll()
        self.draw()

    def close_tab(self, idx: int):
        """
        Close the tab at the given index. If only one tab remains this
        function will simply return without destroying the window. After
        removal the active_tab and active_tab_index are updated and the
        chrome and tab surfaces are re‑rasterized. A redraw is triggered
        to reflect the change. This mirrors the Tkinter version in
        browser.py but omits widget management.
        """
        if idx < 0 or idx >= len(self.tabs):
            return
        # If this is the last tab, do nothing rather than closing the window
        if len(self.tabs) == 1:
            return
        del self.tabs[idx]
        # Adjust the active tab index if necessary
        if self.active_tab_index > idx:
            self.active_tab_index -= 1
        # Clamp the active tab index
        if self.active_tab_index >= len(self.tabs):
            self.active_tab_index = len(self.tabs) - 1
        # Update the active_tab reference
        self.active_tab = self.tabs[self.active_tab_index] if self.tabs else None
        # Raster surfaces to reflect removal
        self.raster_chrome()
        if self.active_tab:
            self.raster_tab()
        self.draw()

    def new_tab(self, url):
        # Create a real Tab bound to this Browser (not a numeric height).
        new_tab = Tab(self)
        self.tabs.append(new_tab)
        # Keep both index-based and object-based notions of active tab for compatibility.
        self.active_tab_index = len(self.tabs) - 1
        self.active_tab = new_tab
        new_tab.load(url)
        self.raster_chrome()
        self.raster_tab()
        self.draw()

    def current_tab(self):
        return self.tabs[self.active_tab_index] if self.tabs else None

    def raster_tab(self):
        tab_height = math.ceil(
            self.active_tab.document.height + 2*VSTEP)

        if not self.tab_surface or \
                tab_height != self.tab_surface.height():
            self.tab_surface = skia.Surface(WIDTH, tab_height)

        canvas = self.tab_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)
        self.active_tab.raster(canvas)

    def raster_chrome(self):
        canvas = self.chrome_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)

        for cmd in self.chrome.paint():
            cmd.execute(canvas)

    def draw(self):
        canvas = self.root_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)
        
        tab_rect = skia.Rect.MakeLTRB(
            0, self.chrome.bottom, WIDTH, HEIGHT)
        tab_offset = self.chrome.bottom - self.active_tab.scroll
        canvas.save()
        canvas.clipRect(tab_rect)
        canvas.translate(0, tab_offset)
        self.tab_surface.draw(canvas, 0, 0)
        canvas.restore()

        chrome_rect = skia.Rect.MakeLTRB(
            0, 0, WIDTH, self.chrome.bottom)
        canvas.save()
        canvas.clipRect(chrome_rect)
        self.chrome_surface.draw(canvas, 0, 0)
        canvas.restore()

        # This makes an image interface to the Skia surface, but
        # doesn't actually copy anything yet.
        skia_image = self.root_surface.makeImageSnapshot()
        skia_bytes = skia_image.tobytes()

        depth = 32 # Bits per pixel
        pitch = 4 * WIDTH # Bytes per row
        sdl_surface = sdl2.SDL_CreateRGBSurfaceFrom(
            skia_bytes, WIDTH, HEIGHT, depth, pitch,
            self.RED_MASK, self.GREEN_MASK,
            self.BLUE_MASK, self.ALPHA_MASK)

        rect = sdl2.SDL_Rect(0, 0, WIDTH, HEIGHT)
        window_surface = sdl2.SDL_GetWindowSurface(self.sdl_window)
        # SDL_BlitSurface is what actually does the copy.
        sdl2.SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
        sdl2.SDL_UpdateWindowSurface(self.sdl_window)

    def handle_quit(self):
        sdl2.SDL_DestroyWindow(self.sdl_window)

def mainloop(browser):
    event = sdl2.SDL_Event()
    while True:
        while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == sdl2.SDL_QUIT:
                browser.handle_quit()
                sdl2.SDL_Quit()
                sys.exit()
            elif event.type == sdl2.SDL_MOUSEBUTTONUP:
                browser.handle_click(event.button)
            elif event.type == sdl2.SDL_KEYDOWN:
                # Intercept Ctrl/Cmd+C to copy page text to clipboard
                if (event.key.keysym.sym == sdl2.SDLK_c and
                    (event.key.keysym.mod & (sdl2.KMOD_CTRL | sdl2.KMOD_GUI))):
                    browser.copy_to_clipboard()
                elif event.key.keysym.sym == sdl2.SDLK_RETURN:
                    browser.handle_enter()
                elif event.key.keysym.sym == sdl2.SDLK_DOWN:
                    browser.handle_down()
                elif event.key.keysym.sym == sdl2.SDLK_UP:
                    # Scroll up when the up arrow is pressed
                    browser.handle_up()
            elif event.type == sdl2.SDL_MOUSEWHEEL:
                # SDL: positive y = wheel up. Convert to pixel scroll.
                # Trackpads can generate small fractional-ish values; scale and clamp.
                dy = -event.wheel.y * SCROLL_STEP
                if dy != 0:
                    browser.handle_scroll(dy)
            elif event.type == sdl2.SDL_TEXTINPUT:
                browser.handle_key(event.text.text.decode('utf8'))

if __name__ == "__main__":
    sdl2.SDL_Init(sdl2.SDL_INIT_EVENTS)
    browser = Browser()
    browser.new_tab(URL(sys.argv[1]))
    browser.draw()
    mainloop(browser)