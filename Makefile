# =============================================================================
# Anomaly Detection Lab — Makefile 100% Idempotente
#
# QUALQUER comando pode ser executado em QUALQUER ordem.
# Dependências são resolvidas automaticamente.
#
#   make experiment  ← roda setup + up + testes + análise se necessário
#   make up          ← roda setup se necessário
#   make test-burst  ← roda up se necessário
#   make detect      ← avisa se não há datasets
# =============================================================================

include .env
export

DOCKER_NET  := host
STAMP_DIR   := .stamps

# =============================================================================
# GUARDS — verificam estado e falham com mensagem clara
# =============================================================================

define check_docker
	@command -v docker >/dev/null 2>&1 || \
		{ echo "✗ Docker não instalado. Rode: ./setup.sh"; exit 1; }
	@docker info >/dev/null 2>&1 || \
		{ echo "✗ Docker daemon não está rodando. Rode: sudo systemctl start docker"; exit 1; }
endef

define check_k3d
	@command -v k3d >/dev/null 2>&1 || \
		{ echo "✗ k3d não instalado. Rode: ./setup.sh"; exit 1; }
endef

define check_kubectl
	@command -v kubectl >/dev/null 2>&1 || \
		{ echo "✗ kubectl não instalado. Rode: ./setup.sh"; exit 1; }
endef

define check_cluster
	$(call check_docker)
	$(call check_k3d)
	$(call check_kubectl)
	@k3d cluster list 2>/dev/null | grep -q $(CLUSTER_NAME) || \
		{ echo "✗ Cluster '$(CLUSTER_NAME)' não existe. Rodando 'make up'..."; $(MAKE) up; }
endef

define check_images
	@docker image inspect $(APP_IMAGE) >/dev/null 2>&1 || \
		{ echo "→ Imagem FastAPI não encontrada. Buildando..."; $(MAKE) build; }
	@docker image inspect $(ANALYSIS_IMAGE) >/dev/null 2>&1 || \
		{ echo "→ Imagem Analysis não encontrada. Buildando..."; $(MAKE) build-analysis; }
endef

define check_datasets
	@ls datasets/*.csv >/dev/null 2>&1 || \
		{ echo "✗ Nenhum dataset em datasets/. Rode primeiro: make experiment"; exit 1; }
endef

define check_setup
	@chmod +x setup.sh && ./setup.sh
endef

.PHONY: setup up down server-up server-down \
        build build-analysis deploy \
        test-burst test-ramp test-shift \
        detect experiment experiment-quick \
        client-experiment status logs clean help

# =============================================================================
# SETUP — idempotente, pode rodar N vezes
# =============================================================================

setup:
	@chmod +x setup.sh
	@./setup.sh

$(STAMP_DIR):
	@mkdir -p $(STAMP_DIR)

# =============================================================================
# UP — resolve TUDO: setup → cluster → build → deploy
# =============================================================================

up: | $(STAMP_DIR)
	$(call check_docker)
	$(call check_setup)
	$(call check_k3d)
	$(call check_kubectl)
	@# ── Cluster ──
	@if k3d cluster list 2>/dev/null | grep -q $(CLUSTER_NAME); then \
		if docker port k3d-$(CLUSTER_NAME)-serverlb 2>/dev/null | grep -q ":$(APP_PORT)"; then \
			echo "→ Cluster já existe com portas corretas"; \
		else \
			echo "✗ Cluster existe mas com portas ERRADAS (mudou o .env?)"; \
			echo "  Rode: make down && make up"; \
			exit 1; \
		fi; \
	else \
		echo "→ Criando cluster..."; \
		mkdir -p $(HOME)/.kube; \
		if [ ! -w "$(HOME)/.kube" ]; then sudo chown -R $(USER) $(HOME)/.kube; fi; \
		k3d cluster create --config $(K3D_CONFIG) || \
			{ echo "✗ Falha ao criar cluster. Porta em uso? Rode: make down && make up"; exit 1; }; \
		echo "→ Aguardando API server..."; \
		until kubectl cluster-info >/dev/null 2>&1; do sleep 2; done; \
		sleep 5; \
		echo "→ metrics-server..."; \
		kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null || true; \
		kubectl patch deployment metrics-server -n kube-system \
			--type='json' \
			-p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' \
			2>/dev/null || true; \
	fi
	@# ── Build app ──
	@if docker image inspect $(APP_IMAGE) >/dev/null 2>&1; then \
		echo "→ Imagem FastAPI já existe"; \
	else \
		echo "→ Build FastAPI..."; \
		docker build -q -t $(APP_IMAGE) ./app; \
	fi
	@k3d image import $(APP_IMAGE) -c $(CLUSTER_NAME) 2>/dev/null || true
	@# ── Build analysis ──
	@if docker image inspect $(ANALYSIS_IMAGE) >/dev/null 2>&1; then \
		echo "→ Imagem Analysis já existe"; \
	else \
		echo "→ Build Analysis..."; \
		docker build -q -t $(ANALYSIS_IMAGE) ./scripts; \
	fi
	@# ── Deploy ──
	@echo "→ Aplicando manifests..."
	@kubectl apply -f k8s/namespace.yaml
	@kubectl apply -f k8s/monitoring/prometheus.yaml
	@kubectl apply -f k8s/monitoring/grafana.yaml
	@kubectl apply -f k8s/app/deployment.yaml
	@# ── Wait ──
	@echo "→ Aguardando pods..."
	@kubectl wait --for=condition=ready pod -l app=fastapi -n $(NAMESPACE) --timeout=120s 2>/dev/null || true
	@kubectl wait --for=condition=ready pod -l app=prometheus -n $(NAMESPACE) --timeout=120s 2>/dev/null || true
	@kubectl wait --for=condition=ready pod -l app=grafana -n $(NAMESPACE) --timeout=120s 2>/dev/null || true
	@sleep 3
	@touch $(STAMP_DIR)/up
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  Lab READY                                                  ║"
	@echo "║  App:        http://$(CLUSTER_HOST):$(APP_PORT)/health      ║"
	@echo "║  Prometheus: http://$(CLUSTER_HOST):$(PROM_PORT)            ║"
	@echo "║  Grafana:    http://$(CLUSTER_HOST):$(GRAFANA_PORT)         ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"

down:
	@k3d cluster delete $(CLUSTER_NAME) 2>/dev/null || true
	@rm -f $(STAMP_DIR)/up
	@echo "✓ Destruído"

# Aliases para topologia VPS
server-up: up
server-down: down

# =============================================================================
# BUILD — idempotentes, só rebuildam se forçado
# =============================================================================

build:
	$(call check_docker)
	@echo "→ Build FastAPI..."
	@docker build -q -t $(APP_IMAGE) ./app
	@k3d image import $(APP_IMAGE) -c $(CLUSTER_NAME) 2>/dev/null || true
	@echo "✓ FastAPI OK"

build-analysis:
	$(call check_docker)
	@echo "→ Build Analysis..."
	@docker build -q -t $(ANALYSIS_IMAGE) ./scripts
	@echo "✓ Analysis OK"

rebuild: build build-analysis
	@echo "✓ Tudo rebuildado"

# =============================================================================
# K6 TESTS — garantem que cluster está UP antes de rodar
# =============================================================================

test-burst:
	$(call check_cluster)
	$(call check_images)
	@mkdir -p results && chmod 777 results
	@echo "→ [K6] BURST → $(APP_URL)"
	@docker run --rm --network $(DOCKER_NET) \
		-v $(PWD)/k6-scripts:/scripts:ro -v $(PWD)/results:/results \
		-e BASE_URL=$(APP_URL) \
		$(K6_IMAGE) run --out json=/results/k6_burst_$$(date +%s).json \
		/scripts/burst-anomaly.js || true

test-ramp:
	$(call check_cluster)
	$(call check_images)
	@mkdir -p results && chmod 777 results
	@echo "→ [K6] RAMP-UP → $(APP_URL)"
	@docker run --rm --network $(DOCKER_NET) \
		-v $(PWD)/k6-scripts:/scripts:ro -v $(PWD)/results:/results \
		-e BASE_URL=$(APP_URL) \
		$(K6_IMAGE) run --out json=/results/k6_rampup_$$(date +%s).json \
		/scripts/rampup-irregular.js || true

test-shift:
	$(call check_cluster)
	$(call check_images)
	@mkdir -p results && chmod 777 results
	@echo "→ [K6] SHIFT → $(APP_URL)"
	@docker run --rm --network $(DOCKER_NET) \
		-v $(PWD)/k6-scripts:/scripts:ro -v $(PWD)/results:/results \
		-e BASE_URL=$(APP_URL) \
		$(K6_IMAGE) run --out json=/results/k6_shift_$$(date +%s).json \
		/scripts/load-shifting.js || true

# =============================================================================
# DETECT — garante que há datasets
# =============================================================================

detect:
	$(call check_datasets)
	$(call check_images)
	@mkdir -p results && chmod 777 results
	@docker run --rm \
		-v $(PWD)/datasets:/datasets:ro -v $(PWD)/results:/results \
		$(ANALYSIS_IMAGE) detectors.py --input /datasets/ --output /results/

# =============================================================================
# EXPERIMENT — resolve TUDO: setup → up → 9 rodadas → detect
# =============================================================================

define run_scenario
	@echo ""; \
	echo "══════ $(1) run $(2)/3 → $(APP_URL) ══════"; \
	START=$$(date +%s); \
	docker run --rm --network $(DOCKER_NET) \
		-v $(PWD)/k6-scripts:/scripts:ro \
		-e BASE_URL=$(APP_URL) \
		$(K6_IMAGE) run /scripts/$(3) 2>&1 | tail -5 || true; \
	sleep 15; \
	docker run --rm --network $(DOCKER_NET) \
		-v $(PWD)/datasets:/datasets \
		-e PROMETHEUS_URL=$(PROM_URL) \
		$(ANALYSIS_IMAGE) export_metrics.py \
		--scenario $(4) --duration $(5) --start $$START \
		--output /datasets/$(4)_run$(2).csv; \
	if [ $(2) -lt 3 ] || [ "$(4)" != "shift" ]; then \
		echo "→ Cooldown 2min..."; sleep 120; \
	fi
endef

experiment: up
	@mkdir -p datasets results && chmod 777 datasets results
	$(call run_scenario,BURST,1,burst-anomaly.js,burst,720)
	$(call run_scenario,BURST,2,burst-anomaly.js,burst,720)
	$(call run_scenario,BURST,3,burst-anomaly.js,burst,720)
	$(call run_scenario,RAMPUP,1,rampup-irregular.js,rampup,780)
	$(call run_scenario,RAMPUP,2,rampup-irregular.js,rampup,780)
	$(call run_scenario,RAMPUP,3,rampup-irregular.js,rampup,780)
	$(call run_scenario,SHIFT,1,load-shifting.js,shift,960)
	$(call run_scenario,SHIFT,2,load-shifting.js,shift,960)
	$(call run_scenario,SHIFT,3,load-shifting.js,shift,960)
	@$(MAKE) detect
	@echo ""
	@echo "✓ COMPLETO → results/detection_results.csv"

client-experiment: build-analysis experiment

experiment-quick: up
	@mkdir -p datasets results && chmod 777 datasets results
	$(call run_scenario,BURST,1,burst-anomaly.js,burst,720)
	@$(MAKE) detect

# =============================================================================
# UTIL
# =============================================================================

status:
	$(call check_cluster)
	@kubectl get pods -n $(NAMESPACE) -o wide
	@echo ""; kubectl get hpa -n $(NAMESPACE)
	@echo ""; kubectl top pods -n $(NAMESPACE) 2>/dev/null || true

logs:
	$(call check_cluster)
	@kubectl logs -n $(NAMESPACE) -l app=fastapi -f --tail=50

clean:
	@rm -rf results datasets $(STAMP_DIR)
	@echo "✓ Limpo"

help:
	@echo ""
	@echo "  Qualquer comando resolve suas dependências automaticamente."
	@echo "  Ordem não importa. Tudo idempotente."
	@echo ""
	@echo "    make up                Garante: setup + cluster + build + deploy"
	@echo "    make experiment        Garante: up + 9 rodadas + detectores"
	@echo "    make experiment-quick  Garante: up + 1 rodada burst + detectores"
	@echo "    make test-burst        Garante: up + roda burst"
	@echo "    make detect            Requer: datasets/ com CSVs"
	@echo "    make down              Destrói cluster"
	@echo "    make rebuild           Força rebuild das imagens"
	@echo "    make status            Mostra pods e HPA"
	@echo ""
	@echo "  VPS + Notebook:"
	@echo "    VPS:  make server-up"
	@echo "    NB:   make client-experiment CLUSTER_HOST=<ip>"
