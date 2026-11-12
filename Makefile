PROM_IMAGE ?= prom/prometheus:v2.55.1
AM_IMAGE   ?= prom/alertmanager:v0.27.0
PROMTOOL    = docker run --rm -v $(CURDIR)/prometheus:/p:ro --entrypoint promtool $(PROM_IMAGE)
COMPOSE    ?= docker compose

.PHONY: help up down test lint check demo-flood demo-stall demo-recover alerts

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

up: ## build and start the stack with the simulated queue
	$(COMPOSE) up -d --build
	@echo "Grafana http://localhost:3000  Prometheus http://localhost:9090  Alertmanager http://localhost:9093"

down: ## stop the stack and drop volumes
	$(COMPOSE) down -v

test: ## pytest for the exporter and loadgen
	python3 -m pytest -q

lint: ## ruff
	ruff check .

check: ## promtool, amtool and compose config checks (docker)
	$(PROMTOOL) check config /p/prometheus.yml
	$(PROMTOOL) check rules /p/rules/recording.yml /p/rules/alerts.yml
	$(PROMTOOL) test rules /p/tests.yml
	docker run --rm -v $(CURDIR)/alertmanager:/a:ro --entrypoint amtool $(AM_IMAGE) check-config /a/alertmanager.yml
	$(COMPOSE) config -q

demo-flood: ## producers faster than consumers
	$(COMPOSE) run --rm loadgen flood --url http://queue-exporter:9101
demo-stall: ## consumers stop
	$(COMPOSE) run --rm loadgen stall --url http://queue-exporter:9101
demo-recover: ## add consumers back
	$(COMPOSE) run --rm loadgen recover --url http://queue-exporter:9101

alerts: ## show currently firing alerts
	@curl -s 'http://localhost:9090/api/v1/query?query=ALERTS%7Balertstate%3D%22firing%22%7D' | python3 -m json.tool
