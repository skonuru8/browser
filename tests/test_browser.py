import pytest
from browser.networking import URL
from browser.dom import HTMLParser, Element, Text
from browser.css import CSSParser

# --- Networking Tests ---

def test_url_creation():
    """Test that URLs are parsed into scheme, host, port, and path correctly."""
    # Test HTTP default port
    url1 = URL("http://example.com/index.html")
    assert url1.scheme == "http"
    assert url1.host == "example.com"
    assert url1.port == 80
    assert url1.path == "/index.html"

    # Test HTTPS default port
    url2 = URL("https://google.com")
    assert url2.scheme == "https"
    assert url2.port == 443
    assert url2.path == "/"  # Should default to /

    # Test custom port
    url3 = URL("http://localhost:8080/debug")
    assert url3.host == "localhost"
    assert url3.port == 8080

def test_url_resolution():
    """Test resolving relative URLs against a base URL."""
    base = URL("http://example.com/dir/page.html")

    # Relative path
    res1 = base.resolve("image.png")
    assert str(res1) == "http://example.com/dir/image.png"

    # Absolute path
    res2 = base.resolve("/home")
    assert str(res2) == "http://example.com/home"

    # Full URL
    res3 = base.resolve("https://other.com/foo")
    assert str(res3) == "https://other.com/foo"

    # Parent directory (..)
    res4 = base.resolve("../style.css")
    assert str(res4) == "http://example.com/style.css"


# --- DOM Parsing Tests ---

def test_html_parser_simple():
    """Test parsing a simple HTML string into a DOM tree."""
    html = "<html><body><p>Hello</p></body></html>"
    parser = HTMLParser(html)
    tree = parser.parse()

    # Root should be html
    assert isinstance(tree, Element)
    assert tree.tag == "html"
    
    # Check body
    body = tree.children[0]
    assert isinstance(body, Element)
    assert body.tag == "body"

    # Check paragraph
    p = body.children[0]
    assert isinstance(p, Element)
    assert p.tag == "p"

    # Check text content
    text_node = p.children[0]
    assert isinstance(text_node, Text)
    assert text_node.text == "Hello"

def test_html_parser_attributes():
    """Test that attributes are correctly parsed."""
    html = '<div id="main" class="container"></div>'
    parser = HTMLParser(html)
    tree = parser.parse()
    
    # Depending on implementation, tree might be implicit <html> -> <body> -> <div>
    # Let's find the div
    body = tree.children[0]
    div = body.children[0]
    
    assert div.tag == "div"
    assert div.attributes["id"] == "main"
    assert div.attributes["class"] == "container"


# --- CSS Parsing Tests ---

def test_css_parser():
    """Test parsing simple CSS rules."""
    css = "body { background-color: white; } p { color: blue; }"
    parser = CSSParser(css)
    rules = parser.parse()

    assert len(rules) == 2
    
    # Check first rule (body)
    selector, props = rules[0]
    assert selector.tag == "body"
    assert props["background-color"] == "white"

    # Check second rule (p)
    selector, props = rules[1]
    assert selector.tag == "p"
    assert props["color"] == "blue"