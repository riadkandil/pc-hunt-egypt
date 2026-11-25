"""HTTP helpers: polite fetching (one request at a time per host, delay, retries, robots.txt)."""
import gzip
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
import zlib
from urllib.parse import urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36 PCHunt/1.0")
DELAY = 0.6          # seconds between two requests to the same host
TIMEOUT = 25

_locks = {}
_last = {}
_delay = {}          # per-host delay, raised after HTTP 429
_robots = {}
_guard = threading.Lock()


class HttpError(Exception):
    def __init__(self, code, url, body=""):
        super().__init__(f"HTTP {code} {url}")
        self.code, self.url, self.body = code, url, body


_conns = {}         # parallel connections allowed per host (default 1)


def set_conns(host_or_url, n):
    host = urlparse(host_or_url).netloc or host_or_url
    with _guard:
        _conns[host] = n
        _locks.pop(host, None)


def _host_sem(host):
    with _guard:
        if host not in _locks:
            _locks[host] = threading.BoundedSemaphore(_conns.get(host, 1))
        return _locks[host]


def allowed(url):
    """robots.txt check (cached per host). Unreachable robots.txt = allowed."""
    p = urlparse(url)
    key = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(key)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            txt = _raw(key + "/robots.txt", timeout=10)[1]
            rp.parse(txt.decode("utf-8", "replace").splitlines())
        except Exception:
            rp.parse([])
        _robots[key] = rp
    return rp.can_fetch(UA, url)


def _raw(url, data=None, headers=None, timeout=TIMEOUT):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip, deflate",
         "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            return r.geturl(), body, r.headers
    except urllib.error.HTTPError as e:
        try:
            b = e.read()[:2000].decode("utf-8", "replace")
        except Exception:
            b = ""
        raise HttpError(e.code, url, b) from None


class _Headers(dict):
    """Case-insensitive response headers for the curl transport (like http.client's)."""
    def get(self, k, default=None):
        return super().get(k.lower(), default)

    def __getitem__(self, k):
        return super().__getitem__(k.lower())

    def __contains__(self, k):
        return super().__contains__(k.lower())


_curl_hosts = set()       # hosts where python.exe cannot connect but curl.exe can (seen on this PC)


def _curl(url, data=None, headers=None, timeout=TIMEOUT):
    """Same request through curl.exe (fallback transport)."""
    import subprocess
    import tempfile
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    h.update(headers or {})
    with tempfile.TemporaryDirectory() as d:
        hdr, body = os.path.join(d, "h"), os.path.join(d, "b")
        cmd = ["curl", "-sS", "-L", "--compressed", "-m", str(timeout), "-D", hdr, "-o", body, "-w", "%{http_code} %{url_effective}"]
        for k, v in h.items():
            cmd += ["-H", f"{k}: {v}"]
        if data is not None:
            cmd += ["--data-binary", "@-"]
        p = subprocess.run(cmd + [url], input=data, capture_output=True, timeout=timeout + 10)
        if p.returncode != 0:
            raise OSError(f"curl failed ({p.returncode}): {p.stderr.decode(errors='replace')[:200]}")
        code, final = p.stdout.decode().split(" ", 1)
        hs = _Headers()
        for line in open(hdr, encoding="latin-1").read().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                hs[k.strip().lower()] = v.strip()
        b = open(body, "rb").read() if os.path.exists(body) else b""
    if int(code) >= 400:
        raise HttpError(int(code), url, b[:2000].decode("utf-8", "replace"))
    return final, b, hs


def fetch(url, data=None, headers=None, retries=2, check_robots=False, timeout=TIMEOUT):
    """Fetch url (throttled per host). Returns (final_url, bytes, headers)."""
    if check_robots and not allowed(url):
        raise HttpError(999, url, "disallowed by robots.txt")
    host = urlparse(url).netloc
    sem = _host_sem(host)
    err = None
    attempt = 0
    limited = 0
    while True:
        # request starts on one host are spaced by its delay; at most _conns[host] requests are in flight
        with _guard:
            slot = max(time.time(), _last.get(host, 0) + _delay.get(host, DELAY))
            _last[host] = slot
        time.sleep(max(0.0, slot - time.time()))
        with sem:
            try:
                if host in _curl_hosts:
                    return _curl(url, data, headers, timeout)
                try:
                    return _raw(url, data, headers, timeout)
                except urllib.error.URLError as e:
                    # python.exe connect timeouts on this PC while curl works: switch the host to curl
                    if "10060" in str(e) or "timed out" in str(e).lower():
                        out = _curl(url, data, headers, timeout)
                        _curl_hosts.add(host)
                        return out
                    raise
            except HttpError as e:
                err = e
                if e.code == 429 and limited < 4:
                    # rate limited: slow this host down for the rest of the run and wait before retrying
                    limited += 1
                    _delay[host] = min(_delay.get(host, DELAY) * 2, 8)
                    with _guard:
                        _last[host] = time.time() + 30 * limited
                    continue
                if e.code in (400, 401, 403, 404, 405, 410, 422, 429):
                    raise
            except Exception as e:  # timeouts, resets, DNS
                err = e
        attempt += 1
        if attempt > retries:
            raise err
        time.sleep(1.5 * attempt + random.random())


def text(url, **kw):
    final, body, headers = fetch(url, **kw)
    ctype = headers.get("Content-Type", "") if headers else ""
    enc = "utf-8"
    if "charset=" in ctype:
        enc = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    return final, body.decode(enc, "replace")


def get_json(url, **kw):
    final, body, _ = fetch(url, headers={"Accept": "application/json"}, **kw)
    return json.loads(body.decode("utf-8", "replace"))


def post_json(url, payload, **kw):
    data = json.dumps(payload).encode()
    _, body, _ = fetch(url, data=data, headers={"Content-Type": "application/json",
                                                 "Accept": "application/json"}, **kw)
    return json.loads(body.decode("utf-8", "replace"))
