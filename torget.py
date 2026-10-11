#!/usr/bin/env python3
# HTTPS over Tor's Unix SocksPort: SOCKS5 with a username per circuit (names resolved by Tor), keep-alive.
import random, socket, ssl, struct


class SocksError(Exception):
    pass


def _recvn(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c: raise SocksError("connection closed")
        b += c
    return b


def socks_connect(sock_path, host, port, circuit, timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(sock_path)
    s.sendall(b"\x05\x01\x02")
    if _recvn(s, 2) != b"\x05\x02": raise SocksError("no username auth")
    u = circuit.encode()
    s.sendall(b"\x01" + bytes([len(u)]) + u + b"\x01x")
    if _recvn(s, 2)[1] != 0: raise SocksError("auth refused")
    h = host.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + struct.pack(">H", port))
    rep = _recvn(s, 4)
    if rep[1] != 0: raise SocksError(f"connect failed, reply {rep[1]}")
    _recvn(s, {1: 4, 4: 16}.get(rep[3], 0) or _recvn(s, 1)[0])
    _recvn(s, 2)
    return s


class Https:
    """One TLS connection through one Tor circuit; a failure drops it and the next call takes a new circuit."""

    def __init__(self, sock_path, host, timeout=60, connect_timeout=150):
        self.sock_path, self.host, self.timeout, self.connect_timeout, self.t, self.buf = sock_path, host, timeout, connect_timeout, None, b""
        self.tls, self.circuit = not host.endswith(".onion"), None

    def _open(self):
        # Building a circuit to a busy exit can take minutes; reads on a live one should not. Onions: plain HTTP.
        # A circuit whose exit reached the host is kept for reconnects; a failure rotates it.
        self.circuit = self.circuit or f"c{random.randrange(1 << 40)}"
        try:
            s = socks_connect(self.sock_path, self.host, 443 if self.tls else 80, self.circuit, self.connect_timeout)
        except Exception:
            self.circuit = None
            raise
        self.t, self.buf = (ssl.create_default_context().wrap_socket(s, server_hostname=self.host) if self.tls else s), b""
        self.t.settimeout(self.timeout)

    def close(self):
        if self.t:
            try: self.t.close()
            except OSError: pass
        self.t = None

    def _fill(self):
        c = self.t.recv(65536)
        if not c: raise SocksError("closed by server")
        self.buf += c

    def _line(self):
        while b"\r\n" not in self.buf: self._fill()
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def _take(self, n):
        while len(self.buf) < n: self._fill()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def get(self, path):
        try:
            if not self.t: self._open()
            self.t.sendall(f"GET {path} HTTP/1.1\r\nHost: {self.host}\r\nAccept: application/json\r\n\r\n".encode())
            status = int(self._line().split(b" ", 2)[1])
            hdr = {}
            while (line := self._line()):
                k, _, v = line.partition(b":")
                hdr[k.strip().lower()] = v.strip().lower()
            if hdr.get(b"transfer-encoding") == b"chunked":
                body = b""
                while (n := int(self._line().split(b";")[0], 16)):
                    body += self._take(n); self._line()
                while self._line(): pass
            else:
                body = self._take(int(hdr.get(b"content-length", b"0")))
            if hdr.get(b"connection") == b"close": self.close()
            return status, body
        except Exception:
            self.close()
            raise


def get(sock_path, host, path, timeout=60):
    c = Https(sock_path, host, timeout)
    try: return c.get(path)
    finally: c.close()
