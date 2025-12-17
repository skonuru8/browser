"""JavaScript execution context for the simple browser.

This module wraps the optional DukPy interpreter to provide a very
small DOM-like API to JavaScript code running in pages. It exports
functions that can manipulate the Python DOM and register event
listeners. A synchronous XMLHttpRequest implementation enforces the
same-origin and Content-Security-Policy rules of the browser.

If DukPy is not installed, attempting to construct a :class:`JSContext`
will raise a :class:`RuntimeError`. The rest of the browser will
continue to function without JavaScript support.
"""

from __future__ import annotations

import time
import email.utils
from typing import Any, Dict, List, Tuple, Optional

try:
    import dukpy  # type: ignore
except Exception:
    dukpy = None

from .networking import COOKIE_JAR, URL
from .dom import Element, Text, HTMLParser, tree_to_list
from .css import CSSParser, INHERITED_PROPERTIES


# Runtime script implementing a minimal DOM API in JavaScript. This is
# executed once per JSContext and defines constructors and prototypes
# for Node, Event and XMLHttpRequest. It forwards operations back
# into Python via call_python.
RUNTIME_JS = """
function Node(handle) { this.handle = handle; }
var LISTENERS = {};
Node.prototype.addEventListener = function(type, listener) {
  if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};
  var dict = LISTENERS[this.handle];
  if (!dict[type]) dict[type] = [];
  dict[type].push(listener);
};
// dispatchEvent handles event bubbling. It calls listeners on this
// node, then recurses up the tree if the event hasn’t been stopped.
Node.prototype.dispatchEvent = function(evt) {
  var list = (LISTENERS[this.handle] && LISTENERS[this.handle][evt.type]) || [];
  for (var i = 0; i < list.length; i++) {
    list[i].call(this, evt);
  }
  var do_default = evt.do_default;
  var do_bubble = evt.do_bubble;
  if (do_bubble) {
    var parentHandle = call_python("getParent", this.handle);
    if (parentHandle != -1) {
      var parent = new Node(parentHandle);
      // propagate; merge default flags so that preventDefault anywhere
      // stops the default
      do_default = parent.dispatchEvent(evt) && do_default;
    }
  }
  return do_default;
};
function Event(type) {
  this.type = type;
  this.do_default = true;
  this.do_bubble = true;
}
Event.prototype.preventDefault = function() { this.do_default = false; };
Event.prototype.stopPropagation = function() { this.do_bubble = false; };
// document.querySelectorAll forwards to Python to find matching
// elements; returns an array of Node objects.
document = {
  querySelectorAll: function(sel) {
    var handles = call_python("querySelectorAll", sel.toString());
    var out = [];
    for (var i = 0; i < handles.length; i++) {
      out.push(new Node(handles[i]));
    }
    return out;
  }
};
// Create elements in the document; implemented in Python.
document.createElement = function(tag) {
  var h = call_python("create_element", tag.toString().toLowerCase());
  return new Node(h);
};
// Expose Node.children property: immediate element children only
Object.defineProperty(Node.prototype, "children", {
  get: function() {
    var handles = call_python("children", this.handle);
    var out = [];
    for (var i = 0; i < handles.length; i++) {
      out.push(new Node(handles[i]));
    }
    return out;
  }
});
// Node.innerHTML getter/setter
Object.defineProperty(Node.prototype, "innerHTML", {
  get: function() {
    return call_python("innerHTML_get", this.handle);
  },
  set: function(value) {
    call_python("innerHTML_set", this.handle, value.toString());
  }
});
// Node.outerHTML getter
Object.defineProperty(Node.prototype, "outerHTML", {
  get: function() {
    return call_python("outerHTML_get", this.handle);
  }
});
// Node.id property; forwards to getAttribute/set_attribute
Object.defineProperty(Node.prototype, "id", {
  get: function() {
    return call_python("getAttribute", this.handle, "id");
  },
  set: function(value) {
    call_python("set_attribute", this.handle, "id", value.toString());
  }
});
Node.prototype.getAttribute = function(attr) {
  return call_python("getAttribute", this.handle, attr.toString());
};
Node.prototype.setAttribute = function(attr, val) {
  call_python("set_attribute", this.handle, attr.toString(), val.toString());
};
// Node.appendChild inserts a child at the end of children
Node.prototype.appendChild = function(child) {
  call_python("append_child", this.handle, child.handle);
  return child;
};
// Node.insertBefore inserts a child before the reference node
Node.prototype.insertBefore = function(child, ref) {
  call_python("insert_before", this.handle, child.handle, ref.handle);
  return child;
};
// Node.removeChild detaches a child from this node
Node.prototype.removeChild = function(child) {
  call_python("remove_child", this.handle, child.handle);
  return child;
};
// Document.cookie API: forwards to Python get_cookie/set_cookie
Object.defineProperty(document, "cookie", {
  get: function() {
    return call_python("get_cookie");
  },
  set: function(value) {
    call_python("set_cookie", value.toString());
  }
});
// Minimal XMLHttpRequest implementation (synchronous only)
function XMLHttpRequest() {}
XMLHttpRequest.prototype.open = function(method, url, is_async) {
  if (is_async) throw Error("Asynchronous XHR is not supported");
  this.method = method;
  this.url = url;
};
XMLHttpRequest.prototype.send = function(body) {
  // call the Python handler. body can be null or a string
  this.responseText = call_python("XMLHttpRequest_send",
      this.method, this.url.toString(), body);
};
"""

# Snippet used when dispatching events from Python into JavaScript
EVENT_DISPATCH_JS = "new Node(dukpy.handle).dispatchEvent(new Event(dukpy.type))"


class JSContext:
    """A per-tab JavaScript execution environment."""
    def __init__(self, tab: Any) -> None:
        self.tab = tab
        if dukpy is None:
            raise RuntimeError("DukPy is required for JavaScript support")
        self.interp = dukpy.JSInterpreter()
        # Bi-directional mapping between Python nodes and JS handles
        self.node_to_handle: Dict[Any, int] = {}
        self.handle_to_node: Dict[int, Any] = {}
        # Export Python functions to JS
        self.interp.export_function("querySelectorAll", self.querySelectorAll)
        self.interp.export_function("getAttribute", self.getAttribute)
        self.interp.export_function("innerHTML_set", self.innerHTML_set)
        self.interp.export_function("children", self.children)
        self.interp.export_function("create_element", self.create_element)
        self.interp.export_function("append_child", self.append_child)
        self.interp.export_function("insert_before", self.insert_before)
        self.interp.export_function("remove_child", self.remove_child)
        self.interp.export_function("getParent", self.getParent)
        self.interp.export_function("innerHTML_get", self.innerHTML_get)
        self.interp.export_function("outerHTML_get", self.outerHTML_get)
        self.interp.export_function("set_attribute", self.set_attribute)
        # Cookie API
        self.interp.export_function("get_cookie", self.get_cookie)
        self.interp.export_function("set_cookie", self.set_cookie)
        # XMLHttpRequest
        self.interp.export_function("XMLHttpRequest_send", self.XMLHttpRequest_send)
        # Load runtime
        self.interp.evaljs(RUNTIME_JS)
        # Keep track of variables defined for element IDs
        self.id_vars: List[str] = []

    # Handle management
    def get_handle(self, elt: Any) -> int:
        if elt not in self.node_to_handle:
            h = len(self.node_to_handle)
            self.node_to_handle[elt] = h
            self.handle_to_node[h] = elt
        return self.node_to_handle[elt]

    # Exported functions callable from JS
    def querySelectorAll(self, selector_text: str) -> List[int]:
        # Build selector object
        try:
            selector = CSSParser(selector_text).selector()
        except Exception:
            return []
        nodes = [n for n in tree_to_list(self.tab.nodes, []) if selector.matches(n)]
        return [self.get_handle(n) for n in nodes]

    def getAttribute(self, handle: int, attr: str) -> str:
        node = self.handle_to_node.get(handle)
        if isinstance(node, Element):
            return node.attributes.get(attr, "")
        return ""

    def set_attribute(self, handle: int, attr: str, value: str) -> None:
        node = self.handle_to_node.get(handle)
        if not isinstance(node, Element):
            return
        # Update attribute
        if value is None:
            if attr in node.attributes:
                del node.attributes[attr]
        else:
            node.attributes[attr] = value
        # Update id variables if id changed
        if attr == "id":
            self.update_ids()
        # Re-style and re-render because attributes may change styling
        self.tab.process_scripts_and_styles()
        self.tab.apply_styles_and_render()

    def innerHTML_set(self, handle: int, s: str) -> None:
        node = self.handle_to_node.get(handle)
        if not isinstance(node, Element):
            return
        # Parse new HTML inside a dummy wrapper
        try:
            parsed = HTMLParser("<body>" + s + "</body>").parse()
        except Exception:
            return
        new_children = parsed.children
        # Replace children
        node.children = []
        for c in new_children:
            c.parent = node
        node.children = new_children
        # Update scripts/styles and re-render
        self.tab.process_scripts_and_styles()
        self.tab.apply_styles_and_render()
        self.update_ids()

    def innerHTML_get(self, handle: int) -> str:
        node = self.handle_to_node.get(handle)
        if node is None:
            return ""
        out: List[str] = []
        for child in getattr(node, "children", []):
            out.append(self._serialize(child))
        return "".join(out)

    def outerHTML_get(self, handle: int) -> str:
        node = self.handle_to_node.get(handle)
        if node is None:
            return ""
        return self._serialize(node)

    def _serialize(self, node: Any) -> str:
        if isinstance(node, Text):
            return node.text
        if isinstance(node, Element):
            attrs: List[str] = []
            for k, v in node.attributes.items():
                if v == "":
                    attrs.append(k)
                else:
                    val = v.replace('"', '&quot;')
                    attrs.append(f'{k}="{val}"')
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            if node.tag in HTMLParser.SELF_CLOSING_TAGS:
                return f"<{node.tag}{attr_str}>"
            inner: List[str] = []
            for c in node.children:
                inner.append(self._serialize(c))
            inner_str = "".join(inner)
            return f"<{node.tag}{attr_str}>" + inner_str + f"</{node.tag}>"
        return ""

    def children(self, handle: int) -> List[int]:
        node = self.handle_to_node.get(handle)
        out: List[int] = []
        if isinstance(node, Element):
            for c in node.children:
                if isinstance(c, Element):
                    out.append(self.get_handle(c))
        return out

    def create_element(self, tag: str) -> int:
        new_node = Element(tag, {}, None)
        new_node.style = {k: v for k, v in INHERITED_PROPERTIES.items()}
        return self.get_handle(new_node)

    def append_child(self, parent_handle: int, child_handle: int) -> None:
        parent = self.handle_to_node.get(parent_handle)
        child = self.handle_to_node.get(child_handle)
        if not (isinstance(parent, Element) and child is not None):
            return
        if hasattr(child, "parent") and child.parent is not None:
            try:
                child.parent.children.remove(child)
            except ValueError:
                pass
        child.parent = parent
        parent.children.append(child)
        self.tab.process_scripts_and_styles()
        self.tab.apply_styles_and_render()
        self.update_ids()

    def insert_before(self, parent_handle: int, child_handle: int, ref_handle: int) -> None:
        parent = self.handle_to_node.get(parent_handle)
        child = self.handle_to_node.get(child_handle)
        ref = self.handle_to_node.get(ref_handle)
        if not (isinstance(parent, Element) and child is not None and ref is not None):
            return
        if hasattr(child, "parent") and child.parent is not None:
            try:
                child.parent.children.remove(child)
            except ValueError:
                pass
        child.parent = parent
        try:
            idx = parent.children.index(ref)
        except ValueError:
            parent.children.append(child)
        else:
            parent.children.insert(idx, child)
        self.tab.process_scripts_and_styles()
        self.tab.apply_styles_and_render()
        self.update_ids()

    def remove_child(self, parent_handle: int, child_handle: int) -> None:
        parent = self.handle_to_node.get(parent_handle)
        child = self.handle_to_node.get(child_handle)
        if not (isinstance(parent, Element) and child is not None):
            return
        try:
            parent.children.remove(child)
        except ValueError:
            return
        child.parent = None
        self.tab.process_scripts_and_styles()
        self.tab.apply_styles_and_render()
        self.update_ids()

    def getParent(self, handle: int) -> int:
        node = self.handle_to_node.get(handle)
        if hasattr(node, "parent") and node.parent is not None:
            return self.get_handle(node.parent)
        return -1

    # High-level operations
    def update_ids(self) -> None:
        if dukpy is None:
            return
        # Clear existing variables
        for var in self.id_vars:
            try:
                self.interp.evaljs(f"{var} = undefined;")
            except Exception:
                pass
        self.id_vars = []
        nodes = tree_to_list(self.tab.nodes, []) if getattr(self.tab, 'nodes', None) else []
        for node in nodes:
            if isinstance(node, Element) and "id" in node.attributes:
                varname = node.attributes["id"]
                if not varname or not (varname[0].isalpha() or varname[0] == "_"):
                    continue
                handle = self.get_handle(node)
                try:
                    self.interp.evaljs(f"var {varname} = new Node({handle});")
                    self.id_vars.append(varname)
                except Exception:
                    continue

    def run(self, script: str, code: Optional[str] = None) -> None:
        # Execute a snippet of JavaScript code in the interpreter
        js_code = code if code is not None else script
        try:
            self.interp.evaljs(js_code)
        except Exception as ex:
            # Print but ignore errors to avoid crashing the browser
            print("JS error:", ex)

    def dispatch_event(self, type: str, elt: Any) -> bool:
        handle = self.node_to_handle.get(elt)
        if handle is None:
            return False
        try:
            do_default = self.interp.evaljs(EVENT_DISPATCH_JS, type=type, handle=handle)
        except Exception:
            return False
        return not bool(do_default)

    def XMLHttpRequest_send(self, method: str, url: str, body: Optional[str]) -> str:
        # Resolve URL relative to current tab
        try:
            full_url = self.tab.url.resolve(url)
        except Exception as ex:
            raise Exception(f"Invalid XHR URL: {ex}")
        # Check CSP
        if not self.tab.allowed_request(full_url):
            raise Exception("Cross-origin XHR blocked by CSP")
        # Perform network request
        try:
            ref = str(self.tab.url) if getattr(self.tab, 'url', None) else None
            origin = self.tab.url.origin() if getattr(self.tab, 'url', None) else None
            headers, out = full_url.request(referrer=ref, payload=body, origin=origin)
        except Exception as ex:
            raise Exception(str(ex))
        # Enforce same-origin policy unless Access-Control-Allow-Origin permits
        req_origin = self.tab.url.origin() if getattr(self.tab, 'url', None) else None
        resp_origin = full_url.origin()
        if req_origin is not None and resp_origin != req_origin:
            allow: Optional[str] = None
            for k, v in (headers or {}).items():
                if k.lower() == "access-control-allow-origin":
                    allow = v.strip()
                    break
            if not allow:
                raise Exception("Cross-origin XHR request not allowed")
            if allow != "*" and allow != req_origin:
                raise Exception("Cross-origin XHR request not allowed")
        return out

    # Cookie API
    def get_cookie(self) -> str:
        try:
            origin = self.tab.url.origin()
        except Exception:
            return ""
        now = time.time()
        cookies: List[str] = []
        jar = COOKIE_JAR.get(origin, {})
        expired: List[str] = []
        for name, (val, params) in jar.items():
            # Skip HttpOnly cookies when reading
            if any(k.lower() == 'httponly' for k in params):
                continue
            exp = params.get('expires')
            if exp:
                try:
                    if isinstance(exp, (int, float)):
                        expires_ts = float(exp)
                    else:
                        dt = email.utils.parsedate_to_datetime(str(exp))
                        expires_ts = dt.timestamp()
                except Exception:
                    expires_ts = None
                if expires_ts is not None and now > expires_ts:
                    expired.append(name)
                    continue
            parts: List[str] = [f"{name}={val}"]
            for k, v in params.items():
                if k.lower() == 'httponly':
                    continue
                if v == "":
                    parts.append(k)
                else:
                    parts.append(f"{k}={v}")
            cookies.append("; ".join(parts))
        for name in expired:
            jar.pop(name, None)
        return "; ".join(cookies)

    def set_cookie(self, cookie_str: str) -> None:
        try:
            origin = self.tab.url.origin()
        except Exception:
            return
        cookie_str = str(cookie_str).strip()
        if not cookie_str:
            return
        parts = [p.strip() for p in cookie_str.split(';')]
        if not parts:
            return
        first = parts[0]
        if '=' not in first:
            return
        name, val = first.split('=', 1)
        params: Dict[str, str] = {}
        for part in parts[1:]:
            if not part:
                continue
            if '=' in part:
                k, v = part.split('=', 1)
                params[k.casefold()] = v
            else:
                params[part.casefold()] = ""
        # Ignore attempts to set HttpOnly cookies via JS
        if any(k.lower() == 'httponly' for k in params):
            return
        exp = params.get('expires')
        if exp:
            try:
                dt = email.utils.parsedate_to_datetime(str(exp))
                params['expires'] = dt.timestamp()  # type: ignore[assignment]
            except Exception:
                pass
        COOKIE_JAR.setdefault(origin, {})[name] = (val, params)
