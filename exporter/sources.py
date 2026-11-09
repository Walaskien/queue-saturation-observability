"""Queue sources. Each source returns a dict from sample():

    backlog          int, messages waiting
    consumers        int or None
    enqueued_total   int or None   (monotonic counter)
    processed_total  int or None   (monotonic counter)
    oldest_age       float seconds or None

None means "this backend cannot tell"; the exporter then leaves that metric out
instead of inventing a value. Standard library only.
"""
import base64
import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from collections import deque


class SourceError(Exception):
    pass


class SimulatedQueue:
    """In-process queue for demos and tests. Controlled through POST /control."""

    def __init__(self, producer_rate=5.0, consumers=3, rate_per_consumer=2.5, clock=time.time):
        self.producer_rate = float(producer_rate)
        self.consumers = int(consumers)
        self.rate_per_consumer = float(rate_per_consumer)
        self._clock = clock
        self._last = clock()
        self._messages = deque()  # enqueue timestamps, oldest first
        self._prod_acc = 0.0
        self._cons_acc = 0.0
        self.enqueued_total = 0
        self.processed_total = 0
        self._lock = threading.Lock()

    def step(self, now=None):
        with self._lock:
            now = self._clock() if now is None else now
            dt = max(0.0, now - self._last)
            self._last = now
            self._prod_acc += self.producer_rate * dt
            n_in = int(self._prod_acc)
            self._prod_acc -= n_in
            self._messages.extend([now] * n_in)
            self.enqueued_total += n_in
            self._cons_acc += self.consumers * self.rate_per_consumer * dt
            n_out = min(int(self._cons_acc), len(self._messages))
            self._cons_acc -= int(self._cons_acc)
            for _ in range(n_out):
                self._messages.popleft()
            self.processed_total += n_out

    def configure(self, producer_rate=None, consumers=None):
        with self._lock:
            if producer_rate is not None:
                if producer_rate < 0:
                    raise ValueError("producer_rate must be >= 0")
                self.producer_rate = float(producer_rate)
            if consumers is not None:
                if consumers < 0:
                    raise ValueError("consumers must be >= 0")
                self.consumers = int(consumers)

    def sample(self, now=None):
        self.step(now)
        with self._lock:
            now = self._clock() if now is None else now
            age = (now - self._messages[0]) if self._messages else 0.0
            return {"backlog": len(self._messages), "consumers": self.consumers,
                    "enqueued_total": self.enqueued_total,
                    "processed_total": self.processed_total, "oldest_age": age}


class RabbitMQQueue:
    """One queue via the RabbitMQ management API (GET /api/queues/<vhost>/<name>).

    Needs the rabbitmq_management plugin and a user with the `monitoring` tag.
    The API does not expose the age of the oldest message, so oldest_age is None.
    `fetch` can be replaced in tests.
    """

    def __init__(self, url, vhost, queue, user, password, fetch=None, timeout=5):
        self.path = "%s/api/queues/%s/%s" % (
            url.rstrip("/"), urllib.parse.quote(vhost, safe=""), urllib.parse.quote(queue, safe=""))
        token = base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        self._headers = {"Authorization": "Basic " + token}
        self._timeout = timeout
        self._fetch = fetch or self._http_get

    def _http_get(self, url):
        req = urllib.request.Request(url, headers=self._headers)
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    def sample(self, now=None):
        try:
            d = self._fetch(self.path)
        except Exception as exc:
            raise SourceError("rabbitmq: %s" % exc)
        stats = d.get("message_stats", {})
        backlog = int(d.get("messages_ready", 0)) + int(d.get("messages_unacknowledged", 0))
        return {"backlog": backlog,
                "consumers": int(d.get("consumers", 0)),
                "enqueued_total": stats.get("publish"),
                "processed_total": stats.get("ack"),
                "oldest_age": None}


class RedisListQueue:
    """Length of a Redis list (LLEN) over plain RESP. Optional AUTH via password.

    Redis lists keep no counters or timestamps, so only the backlog is reported.
    """

    def __init__(self, host, port, key, password=None, timeout=3):
        self.host, self.port, self.key = host, int(port), key
        self.password, self.timeout = password, timeout

    @staticmethod
    def _cmd(*parts):
        out = b"*%d\r\n" % len(parts)
        for p in parts:
            b = str(p).encode()
            out += b"$%d\r\n%s\r\n" % (len(b), b)
        return out

    @staticmethod
    def _readline(f):
        line = f.readline()
        if not line:
            raise SourceError("redis: connection closed")
        return line.rstrip(b"\r\n")

    def sample(self, now=None):
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                f = s.makefile("rb")
                if self.password:
                    s.sendall(self._cmd("AUTH", self.password))
                    reply = self._readline(f)
                    if not reply.startswith(b"+"):
                        raise SourceError("redis: auth failed")
                s.sendall(self._cmd("LLEN", self.key))
                reply = self._readline(f)
        except OSError as exc:
            raise SourceError("redis: %s" % exc)
        if not reply.startswith(b":"):
            raise SourceError("redis: unexpected reply %r" % reply[:40])
        return {"backlog": int(reply[1:]), "consumers": None, "enqueued_total": None,
                "processed_total": None, "oldest_age": None}


class FileQueue:
    """A spool directory: one file per message (e.g. documents waiting for import).

    backlog = number of matching files, oldest_age = now - oldest mtime.
    """

    def __init__(self, directory, suffix="", clock=time.time):
        self.directory, self.suffix, self._clock = directory, suffix, clock

    def sample(self, now=None):
        now = self._clock() if now is None else now
        try:
            with os.scandir(self.directory) as it:
                mtimes = [e.stat().st_mtime for e in it
                          if e.is_file() and e.name.endswith(self.suffix)
                          and not e.name.startswith(".")]
        except OSError as exc:
            raise SourceError("file: %s" % exc)
        return {"backlog": len(mtimes), "consumers": None, "enqueued_total": None,
                "processed_total": None,
                "oldest_age": max(0.0, now - min(mtimes)) if mtimes else 0.0}
