"""Drive the simulated queue through named scenarios via POST /control."""
import argparse
import time
import urllib.request

# name -> list of (producer_rate, consumers, seconds)
SCENARIOS = {
    "normal": [(5, 3, 0)],
    # producers run 6x faster than consumers can drain
    "flood": [(45, 3, 0)],
    # consumers die (stuck on a lock, crashed worker, dead downstream)
    "stall": [(5, 0, 0)],
    "recover": [(5, 6, 0)],
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
    for rate, consumers, secs in SCENARIOS[a.scenario]:
        print(control(a.url, rate, consumers))
        time.sleep(secs)


if __name__ == "__main__":
    main()
