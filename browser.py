import socket
import ssl
import sys
import tkinter
import tkinter.font


WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
BLOCK_ELEMENTS = {
    "html",
    "body",
    "article",
    "section",
    "div",
    "h1",
    "h2",
    "p",
    "ul",
    "ol",
    "li",
}


class URL:
    def __init__(self, url):
        self.scheme, rest = url.split("://", 1)
        assert self.scheme in ["http", "https"]

        if "/" in rest:
            host_port, path = rest.split("/", 1)
            self.path = "/" + path
        else:
            host_port = rest
            self.path = "/"

        if ":" in host_port:
            host, port = host_port.split(":", 1)
            self.host = host
            self.port = int(port)
        else:
            self.host = host_port
            self.port = 80 if self.scheme == "http" else 443

    def request(self):
        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        s.connect((self.host, self.port))

        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        request = f"GET {self.path} HTTP/1.0\r\nHost: {self.host}\r\n\r\n"
        s.send(request.encode("utf8"))

        response = s.makefile("r", encoding="utf8", newline="\r\n")
        statusline = response.readline()
        version, status, explanation = statusline.split(" ", 2)

        headers = {}
        while True:
            line = response.readline()
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            headers[header.lower()] = value.strip()

        assert "transfer-encoding" not in headers
        assert "content-encoding" not in headers

        body = response.read()
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
        return f"<{self.tag}>"


class HTMLParser:
    def __init__(self, body):
        self.body = body
        self.unfinished = []

    def parse(self):
        text = ""
        in_tag = False
        for c in self.body:
            if c == "<":
                if text:
                    self.add_text(text)
                    text = ""
                in_tag = True
                current_tag = ""
            elif c == ">" and in_tag:
                in_tag = False
                self.add_tag(current_tag.strip())
            elif in_tag:
                current_tag += c
            else:
                text += c
        if text:
            self.add_text(text)
        return self.finish()

    def add_text(self, text):
        if not text:
            return
        parent = self.unfinished[-1] if self.unfinished else None
        node = Text(text, parent)
        if parent:
            parent.children.append(node)
        else:
            self.unfinished.append(node)

    def add_tag(self, tag):
        if not tag or tag.startswith("!"):
            return

        if tag.startswith("/"):
            if len(self.unfinished) > 1:
                self.unfinished.pop()
            return

        tagname, attributes = self.parse_tag(tag)
        parent = self.unfinished[-1] if self.unfinished else None
        node = Element(tagname, attributes, parent)
        if parent:
            parent.children.append(node)
        self.unfinished.append(node)
        if tag.endswith("/"):
            self.unfinished.pop()

    def parse_tag(self, tag):
        parts = tag.split()
        tagname = parts[0].lower()
        attributes = {}
        for attr in parts[1:]:
            if "=" in attr:
                key, value = attr.split("=", 1)
                attributes[key.lower()] = value.strip("\"'")
            else:
                attributes[attr.lower()] = ""
        return tagname, attributes

    def finish(self):
        if not self.unfinished:
            return Element("html", {}, None)
        while len(self.unfinished) > 1:
            self.unfinished.pop()
        return self.unfinished[0]


def set_style(node, parent_style=None):
    default_style = {
        "font-size": 16,
        "font-style": "roman",
        "font-weight": "normal",
        "display": "inline",
    }
    style = parent_style.copy() if parent_style else default_style.copy()

    if isinstance(node, Element):
        if node.tag in BLOCK_ELEMENTS:
            style["display"] = "block"
        if node.tag in ["i", "em"]:
            style["font-style"] = "italic"
        if node.tag in ["b", "strong"]:
            style["font-weight"] = "bold"
        if node.tag == "small":
            style["font-size"] = max(10, int(style["font-size"] * 0.8))
        if node.tag == "big":
            style["font-size"] = int(style["font-size"] * 1.25)
        if node.tag == "h1":
            style["font-size"] = 32
            style["font-weight"] = "bold"
            style["display"] = "block"
        if node.tag == "h2":
            style["font-size"] = 24
            style["font-weight"] = "bold"
            style["display"] = "block"

    node.style = style
    for child in node.children:
        set_style(child, style)


def get_font(style):
    return tkinter.font.Font(
        size=style.get("font-size", 16),
        weight=style.get("font-weight", "normal"),
        slant=style.get("font-style", "roman"),
    )


class Layout:
    def __init__(self, node, parent):
        self.node = node
        self.parent = parent
        self.children = []
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0

    def display_list(self):
        dl = []
        for child in self.children:
            dl.extend(child.display_list())
        return dl


class DocumentLayout(Layout):
    def __init__(self, node):
        super().__init__(node, None)
        self.width = WIDTH
        self.x = 0
        self.y = 0

    def layout(self):
        cursor_y = VSTEP
        for child in self.node.children:
            if not isinstance(child, Element) or child.style.get("display") != "block":
                continue
            child_layout = BlockLayout(child, self, cursor_y)
            child_layout.layout()
            self.children.append(child_layout)
            cursor_y += child_layout.height
        self.height = cursor_y


class BlockLayout(Layout):
    def __init__(self, node, parent, y):
        super().__init__(node, parent)
        self.y = y

    def layout(self):
        self.x = HSTEP
        self.width = WIDTH - 2 * HSTEP
        cursor_y = self.y

        inline = InlineLayout(self, self.x, cursor_y, self.width)
        for child in self.node.children:
            if isinstance(child, Element) and child.style.get("display") == "block":
                if inline.has_content():
                    inline.layout()
                    self.children.append(inline)
                    cursor_y += inline.height
                    inline = InlineLayout(self, self.x, cursor_y, self.width)

                child_layout = BlockLayout(child, self, cursor_y)
                child_layout.layout()
                self.children.append(child_layout)
                cursor_y += child_layout.height
            else:
                inline.add_inline(child)

        if inline.has_content():
            inline.layout()
            self.children.append(inline)
            cursor_y += inline.height

        self.height = cursor_y - self.y


class InlineLayout(Layout):
    def __init__(self, parent, x, y, width):
        super().__init__(None, parent)
        self.x = x
        self.y = y
        self.width = width
        self.words = []

    def add_inline(self, node):
        self.words.extend(self._collect_words(node))

    def _collect_words(self, node):
        if isinstance(node, Text):
            return [(node.text, node.style)]
        if isinstance(node, Element):
            parts = []
            for child in node.children:
                parts.extend(self._collect_words(child))
            return parts
        return []

    def has_content(self):
        return bool(self.words)

    def layout(self):
        line = LineLayout(self, self.x, self.y, self.width)
        self.children = [line]
        for text, style in self.words:
            for word in self._split_words(text):
                if word == "":
                    continue
                line.add_word(word, style)
        line.finish()
        self.height = line.height

    @staticmethod
    def _split_words(text):
        output = []
        for part in text.split(" "):
            if part:
                output.append(part)
            output.append(" ")
        if output:
            output.pop()
        return output


class LineLayout(Layout):
    def __init__(self, parent, x, y, width):
        super().__init__(None, parent)
        self.x = x
        self.y = y
        self.width = width
        self.cursor_x = x
        self.cursor_y = y
        self.line_height = 0
        self.line = []

    def add_word(self, word, style):
        font = get_font(style)
        w = font.measure(word)
        h = font.metrics("linespace")

        if self.cursor_x + w > self.x + self.width and self.line:
            self.flush()
        self.line.append((word, font, self.cursor_x, h))
        self.cursor_x += w
        self.line_height = max(self.line_height, h)

    def flush(self):
        baseline = self.cursor_y + max(self.line_height, VSTEP)
        for word, font, x, _ in self.line:
            self.children.append(TextLayout(word, font, x, baseline))
        self.cursor_x = self.x
        self.cursor_y = baseline
        self.line_height = 0
        self.line = []

    def finish(self):
        if self.line:
            self.flush()
        self.height = self.cursor_y - self.y


class TextLayout(Layout):
    def __init__(self, word, font, x, y):
        super().__init__(None, None)
        self.word = word
        self.font = font
        self.x = x
        self.y = y
        self.width = font.measure(word)
        self.height = font.metrics("linespace")

    def display_list(self):
        return [(self.x, self.y, self.word, self.font)]


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack()
        self.window.bind("<Down>", self.scrolldown)

        self.scroll = 0
        self.display_list = []

    def draw(self):
        self.canvas.delete("all")
        for x, y, word, font in self.display_list:
            if y > self.scroll + HEIGHT:
                continue
            if y - font.metrics("linespace") < self.scroll:
                continue
            self.canvas.create_text(
                x,
                y - self.scroll,
                text=word,
                font=font,
                anchor="sw",
            )

    def load(self, url):
        body = url.request()
        parser = HTMLParser(body)
        dom = parser.parse()
        set_style(dom)

        layout_root = DocumentLayout(dom)
        layout_root.layout()
        self.display_list = layout_root.display_list()
        self.draw()

    def scrolldown(self, _):
        self.scroll += SCROLL_STEP
        self.draw()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python browser.py URL")
        sys.exit(1)

    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()
