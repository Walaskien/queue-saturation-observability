"""Simulated document-flow queue with a Prometheus /metrics endpoint.

The queue is in-process: producers add messages at `producer_rate` per second,
`consumers` workers each remove `rate_per_consumer` messages per second.
The state can be changed at runtime through POST /control, which is how the
load generator floods or stalls the queue. Standard library only.
"""
import argparse
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class QueueSim:
    def __init__(self, producer_rate=5.0, consumers=3, rate_per_consumer=2.5,
                 clock=time.time):
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
        """Advance the simulation to `now` (default: clock())."""
        with self._lock:
            now = self._clock() if now is None else now
            dt = max(0.0, now - self._last)
            self._last = now
            self._prod_acc += self.producer_rate * dt
            n_in = int(self._prod_acc)
            self._prod_acc -= n_in
            for _ in range(n_in):
                self._messages.append(now)
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

    def render(self, now=None):
        """Return metrics in Prometheus text exposition format."""
        with self._lock:
            now = self._clock() if now is None else now
            backlog = len(self._messages)
            age = (now - self._messages[0]) if self._messages else 0.0
            lines = [
                "# HELP queue_backlog_messages Messages waiting in the queue.",
                "# TYPE queue_backlog_messages gauge",
                "queue_backlog_messages %d" % backlog,
                "# HELP queue_oldest_message_age_seconds Age of the oldest waiting message.",
                "# TYPE queue_oldest_message_age_seconds gauge",
                "queue_oldest_message_age_seconds %.3f" % age,
                "# HELP queue_consumers Active consumer workers.",
                "# TYPE queue_consumers gauge",
                "queue_consumers %d" % self.consumers,
                "# HELP queue_enqueued_total Messages added since start.",
                "# TYPE queue_enqueued_total counter",
                "queue_enqueued_total %d" % self.enqueued_total,
                "# HELP queue_processed_total Messages processed since start.",
                "# TYPE queue_processed_total counter",
                "queue_processed_total %d" % self.processed_total,
            ]
            return "\n".join(lines) + "\n"


def make_handler(sim):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/plain; charset=utf-8"):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/metrics":
                sim.step()
                self._send(200, sim.render(), "text/plain; version=0.0.4")
            elif path == "/healthz":
                self._send(200, "ok\n")
            else:
                self._send(404, "not found\n")

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/control":
                self._send(404, "not found\n")
                return
            q = parse_qs(url.query)
            try:
                rate = float(q["producer_rate"][0]) if "producer_rate" in q else None
                cons = int(q["consumers"][0]) if "consumers" in q else None
                sim.step()
                sim.configure(producer_rate=rate, consumers=cons)
            except (ValueError, IndexError) as exc:
                self._send(400, "bad request: %s\n" % exc)
                return
            self._send(200, "producer_rate=%s consumers=%s\n"
                       % (sim.producer_rate, sim.consumers))

        def log_message(self, fmt, *args):
            pass

    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9101)
    p.add_argument("--producer-rate", type=float, default=5.0)
    p.add_argument("--consumers", type=int, default=3)
    p.add_argument("--rate-per-consumer", type=float, default=2.5)
    a = p.parse_args()
    sim = QueueSim(a.producer_rate, a.consumers, a.rate_per_consumer)

    def ticker():
        while True:
            sim.step()
            time.sleep(0.2)

    threading.Thread(target=ticker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(sim)).serve_forever()


if __name__ == "__main__":
    main()
