from __future__ import annotations
from typing import Optional, Tuple, List, Dict

import argparse
import base64
import http.client
import http.server
import ipaddress
import select
import socket
import socketserver
import urllib.parse


HOP_BY_HOP_HEADERS = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
}


def _parse_host_port(target: str, default_port: int) -> Tuple[str, int]:
    target = target.strip()
    if target.startswith("["):
        # IPv6: [2001:db8::1]:443
        end = target.find("]")
        if end == -1:
            raise ValueError("invalid IPv6 host")
        host = target[1:end]
        rest = target[end + 1 :]
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, default_port
    if ":" in target:
        host, port_s = target.rsplit(":", 1)
        return host, int(port_s)
    return target, default_port


def _read_exact(rfile, n: int) -> bytes:
    data = rfile.read(n)
    if data is None:
        return b""
    if len(data) != n:
        raise ConnectionError("unexpected EOF while reading request body")
    return data


def _read_chunked(rfile, max_size: int) -> bytes:
    body = bytearray()
    while True:
        line = rfile.readline(65537)
        if not line:
            raise ConnectionError("unexpected EOF while reading chunk size")
        if len(line) > 65536:
            raise ValueError("chunk size line too long")
        line = line.strip().split(b";", 1)[0]
        try:
            size = int(line, 16)
        except ValueError as e:
            raise ValueError("invalid chunk size") from e
        if size == 0:
            # trailers
            while True:
                trailer = rfile.readline(65537)
                if not trailer or trailer in (b"\r\n", b"\n"):
                    break
            break
        if size < 0:
            raise ValueError("invalid chunk size")
        if len(body) + size > max_size:
            raise ValueError("request body too large")
        body += _read_exact(rfile, size)
        crlf = _read_exact(rfile, 2)
        if crlf != b"\r\n":
            raise ValueError("invalid chunk terminator")
    return bytes(body)


def _basic_auth_ok(header_value: Optional[str], expected_userpass: str) -> bool:
    if not header_value:
        return False
    try:
        scheme, _, token = header_value.partition(" ")
        if scheme.lower() != "basic":
            return False
        decoded = base64.b64decode(token.strip()).decode("utf-8", errors="strict")
        return decoded == expected_userpass
    except Exception:
        return False


class _ProxyConfig:
    def __init__(
        self,
        listen: str,
        port: int,
        timeout: float,
        auth_userpass: Optional[str],
        max_body: int,
        verbose: bool,
        monitor_interval: float = 10.0,
        monitor_timeout: float = 2.0,
    ) -> None:
        self.listen = listen
        self.port = port
        self.timeout = timeout
        self.auth_userpass = auth_userpass
        self.max_body = max_body
        self.verbose = verbose
        self.monitor_interval = monitor_interval
        self.monitor_timeout = monitor_timeout


def _normalize_listen_addr(addr: str) -> str:
    addr = addr.strip()
    # Allow bracket form like "[::]" for convenience.
    if addr.startswith("[") and addr.endswith("]"):
        addr = addr[1:-1]
    return addr


def _is_ipv6_literal(addr: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(addr), ipaddress.IPv6Address)
    except ValueError:
        return False


def _is_ipv4_literal(addr: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address)
    except ValueError:
        return False


def _guess_primary_local_ip(family: int) -> Optional[str]:
    """Best-effort: pick the local IP used for an outbound route.

    This does not send any packets; it only asks the OS for routing decision.
    """
    s: Optional[socket.socket] = None
    try:
        if family == socket.AF_INET6:
            dest = ("2001:4860:4860::8888", 80, 0, 0)
        else:
            dest = ("1.1.1.1", 80)
        s = socket.socket(family, socket.SOCK_DGRAM)
        s.connect(dest)
        local = s.getsockname()
        return local[0]
    except OSError:
        return None
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def _format_host_for_url(host: str) -> str:
    return f"[{host}]" if _is_ipv6_literal(host) else host


def _print_listen_hints(listen_addr: str, port: int) -> None:
    # Always print the bind target first.
    bind_show = _format_host_for_url(listen_addr)
    print(f"HTTP Proxy listening on {bind_show}:{port}", flush=True)

    # If listening on wildcard, also show best-effort concrete addresses.
    hints: List[str] = []
    if listen_addr in {"0.0.0.0", "::"}:
        v4 = _guess_primary_local_ip(socket.AF_INET)
        v6 = _guess_primary_local_ip(socket.AF_INET6)
        if v4:
            hints.append(f"http://{v4}:{port}")
        if v6:
            hints.append(f"http://[{v6}]:{port}")

    if hints:
        print("可用访问地址（根据本机路由推断）：", flush=True)
        for u in hints:
            print(f"  - {u}", flush=True)


def make_proxy_handler(config: _ProxyConfig):
    class ProxyHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args) -> None:
            if config.verbose:
                super().log_message(format, *args)

        def _require_auth_if_needed(self) -> bool:
            if not config.auth_userpass:
                return True
            if _basic_auth_ok(self.headers.get("Proxy-Authorization"), config.auth_userpass):
                return True
            self.send_response(407, "Proxy Authentication Required")
            self.send_header("Proxy-Authenticate", 'Basic realm="simple-proxy"')
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            return False

        def _connection_header_tokens(self) -> set[str]:
            val = self.headers.get("Connection")
            if not val:
                return set()
            tokens = [t.strip().lower() for t in val.split(",") if t.strip()]
            return set(tokens)

        def _filtered_request_headers(self, host: str) -> Dict[str, str]:
            connection_tokens = self._connection_header_tokens()
            drop = set(HOP_BY_HOP_HEADERS) | connection_tokens
            out: Dict[str, str] = {}
            for k, v in self.headers.items():
                lk = k.lower()
                if lk in drop:
                    continue
                out[k] = v
            out["Host"] = host
            out["Connection"] = "close"
            return out

        def _resolve_target(self) -> tuple[str, str, int, str, str]:
            # returns (scheme, host, port, path_with_query, host_header)
            raw_path = self.path
            if raw_path.startswith("http://") or raw_path.startswith("https://"):
                u = urllib.parse.urlsplit(raw_path)
                scheme = u.scheme.lower()
                if not u.hostname:
                    raise ValueError("missing hostname")
                host = u.hostname
                port = u.port or (443 if scheme == "https" else 80)
                path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
                host_header = host if (u.port is None) else f"{host}:{port}"
                return scheme, host, port, path, host_header

            # origin-form: need Host header
            host_header = self.headers.get("Host")
            if not host_header:
                raise ValueError("missing Host header")
            host, port = _parse_host_port(host_header, 80)
            scheme = "http"
            path = raw_path or "/"
            return scheme, host, port, path, host_header

        def _read_request_body(self) -> Optional[bytes]:
            te = (self.headers.get("Transfer-Encoding") or "").lower()
            if "chunked" in te:
                return _read_chunked(self.rfile, config.max_body)
            cl = self.headers.get("Content-Length")
            if cl is None:
                return None
            try:
                n = int(cl)
            except ValueError as e:
                raise ValueError("invalid Content-Length") from e
            if n < 0 or n > config.max_body:
                raise ValueError("request body too large")
            if n == 0:
                return b""
            return _read_exact(self.rfile, n)

        def _send_upstream_error(self, status: int, msg: str) -> None:
            self.send_response(status)
            self.send_header("Connection", "close")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            body = msg.encode("utf-8", errors="replace")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def _handle_http_method(self) -> None:
            if not self._require_auth_if_needed():
                return
            try:
                scheme, host, port, path, host_header = self._resolve_target()
                headers = self._filtered_request_headers(host_header)
                body = self._read_request_body()
            except ValueError as e:
                self._send_upstream_error(400, str(e))
                return
            except ConnectionError as e:
                self._send_upstream_error(400, str(e))
                return

            conn: Optional[http.client.HTTPConnection] = None
            try:
                if scheme == "https":
                    conn = http.client.HTTPSConnection(host, port, timeout=config.timeout)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=config.timeout)
                conn.request(self.command, path, body=body, headers=headers)
                resp = conn.getresponse()

                self.send_response(resp.status, resp.reason)

                # If http.client de-chunks upstream but keeps TE header, re-chunk ourselves.
                upstream_chunked = bool(getattr(resp, "chunked", False))
                resp_headers = resp.getheaders()
                for k, v in resp_headers:
                    lk = k.lower()
                    if lk in HOP_BY_HOP_HEADERS:
                        continue
                    if upstream_chunked and lk in {"transfer-encoding", "content-length"}:
                        continue
                    self.send_header(k, v)
                self.send_header("Connection", "close")
                if upstream_chunked:
                    self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                if self.command.upper() == "HEAD":
                    self.close_connection = True
                    return

                if upstream_chunked:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                        self.wfile.write(chunk)
                        self.wfile.write(b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    while True:
                        data = resp.read(8192)
                        if not data:
                            break
                        self.wfile.write(data)

                self.close_connection = True
            except (OSError, http.client.HTTPException) as e:
                self._send_upstream_error(502, f"upstream error: {e}")
            finally:
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass

        def _relay(self, client: socket.socket, upstream: socket.socket) -> None:
            client.setblocking(False)
            upstream.setblocking(False)
            sockets = [client, upstream]
            while True:
                r, _, _ = select.select(sockets, [], [], config.timeout)
                if not r:
                    break
                for s in r:
                    try:
                        data = s.recv(8192)
                    except OSError:
                        return
                    if not data:
                        return
                    (upstream if s is client else client).sendall(data)

        def do_CONNECT(self) -> None:
            if not self._require_auth_if_needed():
                return
            try:
                host, port = _parse_host_port(self.path, 443)
            except ValueError:
                self.send_error(400, "invalid CONNECT target")
                return

            upstream: Optional[socket.socket] = None
            try:
                upstream = socket.create_connection((host, port), timeout=config.timeout)
                self.send_response(200, "Connection Established")
                self.send_header("Connection", "close")
                self.end_headers()
                self._relay(self.connection, upstream)
            except OSError as e:
                self._send_upstream_error(502, f"connect failed: {e}")
            finally:
                try:
                    if upstream is not None:
                        upstream.close()
                except Exception:
                    pass
                try:
                    self.connection.close()
                except Exception:
                    pass

        def do_GET(self) -> None:
            self._handle_http_method()

        def do_POST(self) -> None:
            self._handle_http_method()

        def do_PUT(self) -> None:
            self._handle_http_method()

        def do_DELETE(self) -> None:
            self._handle_http_method()

        def do_PATCH(self) -> None:
            self._handle_http_method()

        def do_OPTIONS(self) -> None:
            self._handle_http_method()

        def do_HEAD(self) -> None:
            self._handle_http_method()

    return ProxyHandler


def run_proxy(config: _ProxyConfig) -> None:
    handler_class = make_proxy_handler(config)
    listen_addr = _normalize_listen_addr(config.listen)
    server_address = (listen_addr, config.port)
    # allow fast restart

    server_cls = socketserver.ThreadingTCPServer
    if _is_ipv6_literal(listen_addr):
        class ThreadingTCPServerV6(socketserver.ThreadingTCPServer):
            address_family = socket.AF_INET6

            def server_bind(self) -> None:
                # Best-effort dual-stack (accept IPv4-mapped) when binding to ::
                try:
                    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except OSError:
                    pass
                return super().server_bind()

        server_cls = ThreadingTCPServerV6

    server_cls.allow_reuse_address = True
    with server_cls(server_address, handler_class) as httpd:
        _print_listen_hints(listen_addr, config.port)
        if config.auth_userpass:
            print("Auth enabled: Basic", flush=True)
        httpd.serve_forever()


def _parse_args() -> _ProxyConfig:
    p = argparse.ArgumentParser(description="Simple forward HTTP proxy (supports CONNECT)")
    p.add_argument(
        "--listen",
        default="127.0.0.1",
        help="listen address, e.g. 0.0.0.0 / :: / ::1 / 2001:db8::1 (brackets also ok: [::])",
    )
    p.add_argument("--port", type=int, default=8080, help="listen port")
    p.add_argument(
        "--auth",
        default=None,
        help='enable Basic auth, format: "user:pass" (recommended when listening on 0.0.0.0)',
    )
    p.add_argument("--timeout", type=float, default=60.0, help="socket timeout seconds")
    p.add_argument(
        "--max-body",
        type=int,
        default=32 * 1024 * 1024,
        help="max request body size in bytes (default: 32MiB)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="enable access log")
    p.add_argument(
        "--monitor-interval",
        type=float,
        default=10.0,
        help="address availability check interval in seconds (default: 10.0)",
    )
    p.add_argument(
        "--monitor-timeout",
        type=float,
        default=2.0,
        help="address detection timeout in seconds (default: 2.0)",
    )
    args = p.parse_args()
    return _ProxyConfig(
        listen=_normalize_listen_addr(args.listen),
        port=args.port,
        timeout=args.timeout,
        auth_userpass=args.auth,
        max_body=args.max_body,
        verbose=args.verbose,
        monitor_interval=args.monitor_interval,
        monitor_timeout=args.monitor_timeout,
    )


if __name__ == "__main__":
    run_proxy(_parse_args())
