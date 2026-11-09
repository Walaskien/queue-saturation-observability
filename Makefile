PROM_IMAGE ?= prom/prometheus:v2.55.1
AM_IMAGE   ?= prom/alertmanager:v0.27.0
PROMTOOL    = docker run --rm -v $(CURDIR)/prometheus:/p:ro --entrypoint promtool $(PROM_IMAGE)
COMPOSE    ?= docker compose

.PHONY: up down test lint check demo-flood demo-stall demo-recover alerts

up:
	$(COMPOSE) up -d --build
	@echo "Grafana http://localhost:3000  Prometheus http://localhost:9090  Alertmanager http://localhost:9093"

down:
	$(COMPOSE) down -v

test:
	python3 -m pytest -q

lint:
	ruff check .

check:
	$(PROMTOOL) check config /p/prometheus.yml
	$(PROMTOOL) check rules /p/rules/recording.yml /p/rules/alerts.yml
	$(PROMTOOL) test rules /p/tests.yml
	docker run --rm -v $(CURDIR)/alertmanager:/a:ro --entrypoint amtool $(AM_IMAGE) check-config /a/alertmanager.yml
	$(COMPOSE) config -q

demo-flood:
	$(COMPOSE) run --rm loadgen flood --url http://queue-exporter:9101
demo-stall:
	$(COMPOSE) run --rm loadgen stall --url http://queue-exporter:9101
demo-recover:
	$(COMPOSE) run --rm loadgen recover --url http://queue-exporter:9101

alerts:
	@curl -s 'http://localhost:9090/api/v1/query?query=ALERTS%7Balertstate%3D%22firing%22%7D' | python3 -m json.tool
