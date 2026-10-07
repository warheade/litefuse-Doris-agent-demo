COMPOSE = docker compose -f deploy/docker-compose.yml --env-file .env
PY      = uv run python -m
LABEL  ?= v2
SESSIONS ?= 25

.PHONY: help up down logs wait seed simulate ask experiment compare verify reset

help:
	@echo "make up          start Litefuse (web/worker/pg/redis/minio) -> VeloDB Cloud"
	@echo "make seed        register prompt v1/v2 and the support-golden dataset"
	@echo "make simulate    generate multi-turn agent traffic (SESSIONS=$(SESSIONS), mixed providers/prompts)"
	@echo "make ask Q='..'  ask the agent a single question"
	@echo "make experiment  run the golden dataset (LABEL=v1|v2, PROVIDER=claude|openai)"
	@echo "make compare     run v1 and v2 back to back"
	@echo "make verify      query VeloDB directly to show where the data lives"
	@echo "make down        stop the stack (data kept);  make reset  also wipes local volumes"

.env:
	@test -f .env || (cp .env.example .env && echo "Created .env - fill in VeloDB + LLM settings, then re-run." && exit 1)

up: .env
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory wait

wait:
	@printf "Waiting for Litefuse on http://localhost:3000 "
	@for i in $$(seq 1 90); do \
	  curl -sf http://localhost:3000/api/public/health >/dev/null && echo " ready." && exit 0; \
	  printf "."; sleep 4; done; \
	echo " timed out - check: make logs"; exit 1

logs:
	$(COMPOSE) logs -f --tail=100 litefuse-web litefuse-worker

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

seed:
	$(PY) demo.prompts
	$(PY) demo.eval.dataset

simulate:
	$(PY) demo.simulate --sessions $(SESSIONS) --mix

ask:
	$(PY) demo.agent "$(Q)" $(if $(PROVIDER),--provider $(PROVIDER))

experiment:
	$(PY) demo.eval.run_experiment --label $(LABEL) $(if $(PROVIDER),--provider $(PROVIDER))

compare:
	$(PY) demo.eval.run_experiment --label v1 $(if $(PROVIDER),--provider $(PROVIDER))
	$(PY) demo.eval.run_experiment --label v2 $(if $(PROVIDER),--provider $(PROVIDER))

verify:
	$(PY) demo.verify_velodb
