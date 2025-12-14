import socket
import ssl
import tkinter
import tkinter.font


class URL:
    def __init__(self, url):
        self.scheme, rest = url.split("://", 1)
        assert self.scheme in ["http", "https"]
        if "/" not in rest:
            rest += "/"
        self.host, path = rest.split("/", 1)
        self.path = "/" + path
        self.port = 80 if self.scheme == "http" else 443
        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)

    def resolve(self, url):
        if "://" in url:
            return URL(url)
        elif url.startswith("/"):
            return URL(f"{self.scheme}://{self.host}{url}")
        else:
            parent = self.path.rsplit("/", 1)[0]
            return URL(f"{self.scheme}://{self.host}{parent}/{url}")

    def request(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        s.connect((self.host, self.port))
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        req = f"GET {self.path} HTTP/1.0\r\nHost: {self.host}\r\n\r\n"
        s.send(req.encode("utf8"))
        resp = s.makefile("r", encoding="utf8", newline="\r\n")
        _ = resp.readline()
        headers = {}
        while True:
            line = resp.readline()
            if line == "\r\n":
                break
            k, v = line.split(":", 1)
            headers[k.casefold()] = v.strip()
        assert "transfer-encoding" not in headers
        assert "content-encoding" not in headers
        body = resp.read()
        s.close()
        return body


class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent
        self.style = {}

    def __repr__(self):
        return repr(self.text)


class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.attributes = attributes
        self.children = []
        self.parent = parent
        self.style = {}

    def __repr__(self):
        return "<" + self.tag + ">"


class HTMLParser:
    SELF_CLOSING_TAGS = [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
    HEAD_TAGS = [
        "base",
        "basefont",
        "bgsound",
        "noscript",
        "link",
        "meta",
        "title",
        "style",
        "script",
    ]

    def __init__(self, body):
        self.body = body
        self.unfinished = []

    def parse(self):
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

    def get_attributes(self, text):
        parts = text.split()
        if not parts:
            return "", {}
        tag = parts[0].casefold()
        attributes = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.casefold()] = value
            else:
                attributes[attrpair.casefold()] = ""
        return tag, attributes

    def implicit_tags(self, tag):
        while True:
            open_tags = [node.tag for node in self.unfinished]
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

    def add_text(self, text):
        if text.isspace():
            return
        self.implicit_tags(None)
        parent = self.unfinished[-1] if self.unfinished else None
        if parent is None:
            self.implicit_tags(None)
            parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    def add_tag(self, tagtext):
        if tagtext.startswith("!"):
            return
        tag, attributes = self.get_attributes(tagtext)
        self.implicit_tags(tag)
        if tag.startswith("/"):
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

    def finish(self):
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()


class TagSelector:
    priority = 1

    def __init__(self, tag):
        self.tag = tag

    def matches(self, node):
        return isinstance(node, Element) and node.tag == self.tag


class ClassSelector:
    priority = 10

    def __init__(self, class_name):
        self.class_name = class_name

    def matches(self, node):
        if not isinstance(node, Element):
            return False
        classes = node.attributes.get("class", "")
        return self.class_name in classes.split()


class IdSelector:
    priority = 100

    def __init__(self, id_value):
        self.id_value = id_value

    def matches(self, node):
        return isinstance(node, Element) and node.attributes.get("id", "") == self.id_value


class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.ancestor = ancestor
        self.descendant = descendant
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node):
        if not self.descendant.matches(node):
            return False
        parent = node.parent
        while parent:
            if self.ancestor.matches(parent):
                return True
            parent = parent.parent
        return False


def parse_simple_selector(selector):
    selector = selector.strip()
    if selector.startswith("."):
        return ClassSelector(selector[1:])
    elif selector.startswith("#"):
        return IdSelector(selector[1:])
    else:
        return TagSelector(selector)


def parse_selector(selector_text):
    parts = selector_text.strip().split()
    selector = parse_simple_selector(parts[-1])
    for part in reversed(parts[:-1]):
        selector = DescendantSelector(parse_simple_selector(part), selector)
    return selector


class CSSParser:
    def __init__(self, css):
        self.css = css

    def parse(self):
        rules = []
        i = 0
        css = self.css
        while True:
            start = css.find("{", i)
            if start == -1:
                break
            end = css.find("}", start)
            if end == -1:
                break
            selector_text = css[i:start].strip()
            body_text = css[start + 1 : end]
            for raw_selector in selector_text.split(","):
                selector = parse_selector(raw_selector)
                declarations = self.parse_declarations(body_text)
                rules.append((selector, declarations))
            i = end + 1
        return rules

    @staticmethod
    def parse_declarations(body):
        declarations = {}
        for part in body.split(";"):
            if ":" not in part:
                continue
            prop, value = part.split(":", 1)
            declarations[prop.strip().casefold()] = value.strip()
        return declarations


WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100

BLOCK_ELEMENTS = [
    "html",
    "body",
    "article",
    "section",
    "nav",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hgroup",
    "header",
    "footer",
    "address",
    "p",
    "hr",
    "pre",
    "blockquote",
    "ol",
    "ul",
    "menu",
    "li",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "main",
    "div",
    "table",
    "form",
    "fieldset",
    "legend",
    "details",
    "summary",
]

INHERITED_PROPERTIES = ["font-size", "font-style", "font-weight", "color"]
COLOR_KEYWORDS = {
    "black": "black",
    "gray": "gray",
    "grey": "gray",
    "white": "white",
    "red": "red",
    "green": "green",
    "blue": "blue",
    "yellow": "yellow",
    "purple": "purple",
    "orange": "orange",
}


def parse_color(value, fallback="black"):
    return COLOR_KEYWORDS.get(value.casefold(), fallback)


def parse_font_size(value, parent_size):
    if isinstance(value, (int, float)):
        return int(value)
    if value.endswith("px"):
        return int(float(value[:-2]))
    if value.endswith("em"):
        return int(float(value[:-2]) * parent_size)
    if value.endswith("%"):
        return int(parent_size * float(value[:-1]) / 100.0)
    return parent_size


def get_default_style():
    return {
        "font-size": 16,
        "font-weight": "normal",
        "font-style": "roman",
        "color": "black",
        "background-color": "transparent",
        "display": "inline",
    }


def matches(rule, node):
    selector, _ = rule
    return selector.matches(node)


def style(node, rules, parent_style=None):
    parent_style = parent_style or get_default_style()
    styled = {}
    for prop, value in parent_style.items():
        if prop in INHERITED_PROPERTIES:
            styled[prop] = value
    styled.setdefault("display", "inline")
    styled.setdefault("background-color", "transparent")

    matching = []
    for i, rule in enumerate(rules):
        selector, body = rule
        if selector.matches(node):
            matching.append((selector.priority, i, body))
    matching.sort(key=lambda item: (item[0], item[1]))
    for _, _, body in matching:
        for prop, value in body.items():
            if prop == "font-size":
                styled["font-size"] = parse_font_size(value, styled.get("font-size", 16))
            elif prop == "font-weight":
                styled["font-weight"] = value
            elif prop == "font-style":
                styled["font-style"] = "italic" if value == "italic" else "roman"
            elif prop == "color":
                styled["color"] = parse_color(value, styled.get("color", "black"))
            elif prop == "background-color":
                styled["background-color"] = parse_color(value, "transparent")
            elif prop == "display":
                styled["display"] = value

    if isinstance(node, Element) and node.tag in BLOCK_ELEMENTS:
        styled.setdefault("display", "block")
    else:
        styled.setdefault("display", "inline")

    node.style = styled
    for child in node.children:
        style(child, rules, styled)
    return node


def tree_to_css(node):
    styles = []
    if isinstance(node, Element) and node.tag == "style":
        css_text = "".join(child.text for child in node.children if isinstance(child, Text))
        styles.append(css_text)
    for child in node.children:
        styles.extend(tree_to_css(child))
    return styles


def tree_to_links(node):
    links = []
    if (
        isinstance(node, Element)
        and node.tag == "link"
        and node.attributes.get("rel", "").casefold() == "stylesheet"
        and "href" in node.attributes
    ):
        links.append(node.attributes["href"])
    for child in node.children:
        links.extend(tree_to_links(child))
    return links


FONTS = {}


def get_font(size, weight, style_value):
    key = (size, weight, style_value)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=style_value)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []
        self.x = self.y = self.width = self.height = None

    def layout(self):
        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        self.width = WIDTH - 2 * HSTEP
        self.x = HSTEP
        self.y = VSTEP
        child.layout()
        self.height = child.height

    def paint(self):
        return []


class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []
        self.display_list = []  # (x,y,word,font,color) for inline blocks
        self.x = self.y = self.width = self.height = None
        self.cursor_x = self.cursor_y = 0
        self.line = []

    def layout_mode(self):
        if isinstance(self.node, Text):
            return "inline"
        if any(
            isinstance(child, Element) and child.style.get("display") == "block"
            for child in self.node.children
        ):
            return "block"
        if self.node.children:
            return "inline"
        return "block"

    def layout(self):
        self.x = self.parent.x
        self.width = self.parent.width
        self.y = (self.previous.y + self.previous.height) if self.previous else self.parent.y

        mode = self.layout_mode()
        if mode == "block":
            previous = None
            for child in self.node.children:
                next_block = BlockLayout(child, self, previous)
                self.children.append(next_block)
                previous = next_block
        else:
            self.cursor_x = 0
            self.cursor_y = 0
            self.line = []
            self.recurse(self.node)
            self.flush()

        for child in self.children:
            child.layout()

        if mode == "block":
            self.height = sum(child.height for child in self.children) if self.children else VSTEP
        else:
            if self.display_list:
                any_font = self.display_list[0][3]
                self.height = (self.display_list[-1][1] - self.y) + any_font.metrics("linespace")
            else:
                self.height = VSTEP

    def recurse(self, node):
        if isinstance(node, Text):
            for word in node.text.split():
                self.word(word, node.style)
        elif isinstance(node, Element):
            if node.tag == "br":
                self.flush()
            else:
                for child in node.children:
                    self.recurse(child)

    def word(self, word, style_dict):
        font = get_font(
            style_dict.get("font-size", 16),
            style_dict.get("font-weight", "normal"),
            style_dict.get("font-style", "roman"),
        )
        color = style_dict.get("color", "black")
        w = font.measure(word)
        if self.cursor_x + w > self.width and self.line:
            self.flush()
        self.line.append((self.cursor_x, word, font, color))
        self.cursor_x += w + font.measure(" ")

    def flush(self):
        if not self.line:
            return
        metrics = [font.metrics() for _, _, font, _ in self.line]
        max_ascent = max(m["ascent"] for m in metrics)
        max_descent = max(m["descent"] for m in metrics)
        baseline = self.cursor_y + max_ascent
        for rel_x, word, font, color in self.line:
            x = self.x + rel_x
            y = self.y + baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font, color))
        self.cursor_y = baseline + int(1.25 * max_descent)
        self.cursor_x = 0
        self.line = []

    def paint(self):
        cmds = []
        if isinstance(self.node, Element):
            bgcolor = self.node.style.get("background-color", "transparent")
            if bgcolor != "transparent":
                x2, y2 = self.x + self.width, self.y + self.height
                cmds.append(DrawRect(self.x, self.y, x2, y2, bgcolor))
        if self.layout_mode() == "inline":
            for x, y, word, font, color in self.display_list:
                cmds.append(DrawText(x, y, word, font, color))
        return cmds


class DrawText:
    def __init__(self, x1, y1, text, font, color):
        self.top = y1
        self.left = x1
        self.text = text
        self.font = font
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_text(
            self.left,
            self.top - scroll,
            text=self.text,
            font=self.font,
            fill=self.color,
            anchor="nw",
        )


class DrawRect:
    def __init__(self, x1, y1, x2, y2, color):
        self.top = y1
        self.left = x1
        self.bottom = y2
        self.right = x2
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.left,
            self.top - scroll,
            self.right,
            self.bottom - scroll,
            width=0,
            fill=self.color,
        )


def paint_tree(layout_object, display_list):
    display_list.extend(layout_object.paint())
    for child in layout_object.children:
        paint_tree(child, display_list)


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack()
        self.scroll = 0
        self.display_list = []
        self.window.bind("<Down>", self.scrolldown)

    def load(self, url):
        body = url.request()
        nodes = HTMLParser(body).parse()

        rules = []
        rules.extend(USER_AGENT_STYLES)
        for css_text in tree_to_css(nodes):
            rules.extend(CSSParser(css_text).parse())
        for link in tree_to_links(nodes):
            try:
                css_body = url.resolve(link).request()
                rules.extend(CSSParser(css_body).parse())
            except Exception:
                continue

        styled_nodes = style(nodes, rules)
        self.document = DocumentLayout(styled_nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for cmd in self.display_list:
            cmd.execute(self.scroll, self.canvas)

    def scrolldown(self, e):
        self.scroll += SCROLL_STEP
        self.draw()


USER_AGENT_STYLES = CSSParser(
    """
    html, body { display: block; }
    h1 { display: block; font-size: 2em; font-weight: bold; }
    h2 { display: block; font-size: 1.5em; font-weight: bold; }
    p { display: block; }
    i, em { font-style: italic; }
    b, strong { font-weight: bold; }
    small { font-size: 0.8em; }
    big { font-size: 1.2em; }
    """
).parse()

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python3 browser.py <URL>")
        raise SystemExit(1)
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()
