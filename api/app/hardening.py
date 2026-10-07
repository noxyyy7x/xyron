"""Extra protection for when XYRON is reachable from the internet.

- the real visitor address when a proxy such as Caddy sits in front (so rate limits and the audit log are per visitor, not per proxy)
- refusal of cross-site requests that change something (a defence on top of the SameSite cookie, which other subdomains can slip past)
- more security headers, including HSTS once the site is on HTTPS
- a cap on request size, and an optional list of allowed host names
"""
import ipaddress
import os
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import COOKIE_SECURE, PUBLIC_BASE_URL

MAX_BODY = 1_000_000
CHANGING = ("POST", "PUT", "PATCH", "DELETE")


def _networks(text):
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if part:
            try:
                out.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                pass
    return out


def trusted_networks():
    # the proxy talks to us from this machine (or from Docker's own network), so only those may vouch for a visitor's address
    return _networks(os.getenv("TRUSTED_PROXIES", "127.0.0.0/8,::1/128,172.16.0.0/12"))


def _is_trusted(addr, nets):
    return any(addr in n for n in nets)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    nets = trusted_networks()
    if not _is_trusted(peer_addr, nets):
        return peer  # a visitor talking to us directly can write anything in a header; ignore it
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):  # the right-hand end was added by our own proxy, the left-hand end by whoever called it
        try:
            addr = ipaddress.ip_address(hop)
        except ValueError:
            return peer
        if not _is_trusted(addr, nets):
            return str(addr)
    return peer


def is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    try:
        peer = ipaddress.ip_address(request.client.host) if request.client else None
    except ValueError:
        peer = None
    return bool(peer and _is_trusted(peer, trusted_networks()) and request.headers.get("x-forwarded-proto", "").lower() == "https")


def _blocked(detail, status):
    return JSONResponse({"detail": detail}, status_code=status)


async def origin_guard(request: Request, call_next):
    """A request that changes something must come from this site itself."""
    if request.method in CHANGING:
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        bad = False
        if origin:
            if origin == "null":
                bad = True
            else:
                allowed = {request.headers.get("host", "").lower(), urlparse(PUBLIC_BASE_URL).netloc.lower()}
                bad = urlparse(origin).netloc.lower() not in allowed
        elif fetch_site and fetch_site not in ("same-origin", "none"):
            bad = True
        if bad:
            return _blocked("Cross-site request blocked", 403)
    return await call_next(request)


async def body_limit(request: Request, call_next):
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY:
        return _blocked("Request too large", 413)
    return await call_next(request)


async def host_guard(request: Request, call_next):
    """If ALLOWED_HOSTS is set (for example xyron.example.com), any other Host name is refused."""
    allowed = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()}
    if allowed and request.headers.get("host", "").lower().split(":")[0] not in allowed:
        return _blocked("Unknown host", 400)
    return await call_next(request)


async def extra_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=(), payment=(), usb=()")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "private, no-store")
    if COOKIE_SECURE and is_https(request):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
    return resp
