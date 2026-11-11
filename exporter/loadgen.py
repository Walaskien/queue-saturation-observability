"""Drive the simulated queue through named scenarios via POST /control."""
import argparse
import urllib.request

# name -> (producer_rate msg/s, consumers)
SCENARIOS = {
    "normal": (5, 3),
    "flood": (45, 3),  # 3 consumers drain 7.5 msg/s, so producers are 6x faster
    "stall": (5, 0),
    "recover": (5, 6),
}


def control(base, rate, consumers):
    url = "%s/control?producer_rate=%s&consumers=%s" % (base, rate, consumers)
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode().strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenario", choices=sorted(SCENARIOS))
    p.add_argument("--url", default="http://localhost:9101")
    a = p.parse_args()
    rate, consumers = SCENARIOS[a.scenario]
    print(control(a.url, rate, consumers))


if __name__ == "__main__":
    main()
