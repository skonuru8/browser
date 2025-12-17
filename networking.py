"""Networking utilities for the simple browser.

This module defines the URL class for parsing and resolving HTTP/HTTPS
URLs and performing basic HTTP requests. It also exposes a global
cookie jar (``COOKIE_JAR``) that stores cookies per origin. Cookies
are sent with requests made through :meth:`URL.request` and stored
based on ``Set-Cookie`` headers in the response.

The implementation mirrors the logic from the original monolithic
browser, but isolates networking concerns in a standalone module.
"""

from __future__ import annotations

import socket
import ssl
import time
import email.utils
from typing import Dict, Tuple, Optional

# Cookie jar type: maps origin → cookie name → (value, params)
COOKIE_JAR: Dict[str, Dict[str, Tuple[str, Dict[str, str]]]] = {}


class URL:
    """A simple URL parser and request helper.

    ``URL`` objects know how to resolve relative URLs, determine their
    origin, and make synchronous HTTP/HTTPS requests. Cookies are sent
    and stored via the global :data:`COOKIE_JAR`.
    """

    def __init__(self, url: str) -> None:
        # Split scheme and the rest of the URL
        self.scheme, rest = url.split("://", 1)
        assert self.scheme in ["http", "https"], f"Unsupported scheme: {self.scheme}"
        # Ensure there's at least one '/' to separate host and path
        if "/" not in rest:
            rest += "/"
        self.host, path = rest.split("/", 1)
        self.path = "/" + path
        # Default ports: 80 for HTTP, 443 for HTTPS
        self.port = 80 if self.scheme == "http" else 443
        # If host includes a port, parse it
        if ":" in self.host:
            self.host, p = self.host.split(":", 1)
            self.port = int(p)

    def origin(self) -> str:
        """Return the origin (scheme://host:port) of this URL."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def request(
        self,
        referrer: Optional[str] = None,
        payload: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> Tuple[Dict[str, str], str]:
        """Make an HTTP or HTTPS request to this URL.

        :param referrer: The Referer header value, if any.
        :param payload: If provided, sends a POST with this body;
                        otherwise a GET request is made.
        :param origin: The Origin header value for CORS requests.
        :returns: A tuple of (headers dict, body string).
        :raises ssl.SSLError: If SSL/TLS handshake fails.
        :raises Exception: For other network errors.
        """
        # Establish a TCP connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        sock.connect((self.host, self.port))
        # Wrap with SSL if needed
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            try:
                sock = ctx.wrap_socket(sock, server_hostname=self.host)
            except ssl.SSLError:
                sock.close()
                raise
        # Build HTTP request line and headers
        method = "POST" if payload is not None else "GET"
        req = f"{method} {self.path} HTTP/1.0\r\nHost: {self.host}\r\n"
        # Referer header
        if referrer:
            req += f"Referer: {referrer}\r\n"
        # Origin header for CORS
        if origin:
            req += f"Origin: {origin}\r\n"
        # Send cookies from the jar
        jar_key = self.origin()
        cookies: list[str] = []
        now = time.time()
        jar = COOKIE_JAR.get(jar_key, {})
        # Determine if this request is cross-site relative to the referrer
        ref_origin = None
        if referrer:
            try:
                ref_origin = URL(referrer).origin()
            except Exception:
                ref_origin = None
        cross_site = ref_origin is not None and ref_origin != jar_key
        remove_names: list[str] = []
        for name, (value, params) in jar.items():
            # Skip expired cookies
            exp = params.get('expires')
            if exp:
                try:
                    expires_ts = float(exp) if not isinstance(exp, (str, bytes)) else float(exp)
                except Exception:
                    try:
                        dt = email.utils.parsedate_to_datetime(str(exp))
                        expires_ts = dt.timestamp()
                    except Exception:
                        expires_ts = None
                if expires_ts is not None and now > expires_ts:
                    remove_names.append(name)
                    continue
            # SameSite=Lax cookies are not sent on cross-site POST requests
            same_site = params.get('samesite', '').lower()
            if same_site == 'lax' and method == 'POST' and cross_site:
                continue
            cookies.append(f"{name}={value}")
        # Purge expired cookies
        for n in remove_names:
            jar.pop(n, None)
        if cookies:
            req += f"Cookie: {'; '.join(cookies)}\r\n"
        # POST body headers
        if payload is not None:
            length = len(payload.encode("utf8"))
            req += "Content-Type: application/x-www-form-urlencoded\r\n"
            req += f"Content-Length: {length}\r\n"
        # End of headers
        req += "\r\n"
        # Append body for POST
        if payload is not None:
            req += payload
        # Send request
        sock.send(req.encode("utf8"))
        # Read response
        resp = sock.makefile("r", encoding="utf8", newline="\r\n")
        # Skip status line
        _ = resp.readline()
        headers: Dict[str, str] = {}
        while True:
            line = resp.readline()
            if line == "\r\n" or line == "":
                break
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k_lower = k.casefold()
            v = v.strip()
            if k_lower in headers and k_lower == "set-cookie":
                headers[k_lower] += ", " + v
            else:
                headers[k_lower] = v
        # Body: no transfer encoding expected
        body = resp.read()
        sock.close()
        # Store cookies from Set-Cookie header
        sc = headers.get("set-cookie")
        if sc:
            cookie_headers = [x.strip() for x in sc.split(",")]
            for cookie_str in cookie_headers:
                if not cookie_str:
                    continue
                parts = [p.strip() for p in cookie_str.split(";")]
                if not parts:
                    continue
                name_value = parts[0]
                if "=" not in name_value:
                    continue
                name, val = name_value.split("=", 1)
                params: Dict[str, str] = {}
                for part in parts[1:]:
                    if not part:
                        continue
                    if "=" in part:
                        k_p, v_p = part.split("=", 1)
                        key = k_p.casefold()
                        params[key] = v_p
                    else:
                        key = part.casefold()
                        params[key] = ""
                # Convert Expires to timestamp if possible
                if 'expires' in params:
                    exp_val = params['expires']
                    try:
                        dt = email.utils.parsedate_to_datetime(str(exp_val))
                        params['expires'] = dt.timestamp()
                    except Exception:
                        pass
                COOKIE_JAR.setdefault(jar_key, {})[name] = (val, params)
        return headers, body

    def resolve(self, url: str) -> 'URL':
        """Resolve a relative or protocol-relative URL against this URL."""
        if "://" in url:
            return URL(url)
        if url.startswith("//"):
            return URL(self.scheme + ":" + url)
        if not url.startswith("/"):
            dir_path, _ = self.path.rsplit("/", 1)
            while url.startswith("../"):
                _, url = url.split("/", 1)
                if "/" in dir_path:
                    dir_path, _ = dir_path.rsplit("/", 1)
            url = dir_path + "/" + url
        return URL(f"{self.scheme}://{self.host}:{self.port}{url}")

    def __str__(self) -> str:
        show_port = (
            (self.scheme == "http" and self.port != 80)
            or (self.scheme == "https" and self.port != 443)
        )
        port = f":{self.port}" if show_port else ""
        return f"{self.scheme}://{self.host}{port}{self.path}"
