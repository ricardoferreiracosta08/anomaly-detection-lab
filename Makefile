# =============================================================================
# Anomaly Detection Lab — Makefile 100% idempotente
#
# QUALQUER alvo pode ser executado em QUALQUER ordem: cada um resolve as
# próprias dependências ou falha com uma mensagem clara.
#
# Papéis (ROLE no .env):
#   local   tudo nesta máquina (cluster + carga + análise)
#   server  VPS: só o cluster (app, Prometheus, Grafana, detector online, HPA)
#   client  notebook: carga (k6) + análise; fala com a VPS pela VPN
#
#   make help   ← lista completa
# =============================================================================

SHELL := /bin/bash

ifeq (,$(wildcard .env))
$(error .env não encontrado. Rode: cp .env.example .env  (e ajuste ROLE/CLUSTER_HOST))
endif
include .env
export

ROLE        ?= local
# .env antigo sem a variável: piso do σ do detector online no padrão (0 = desligado)
DETECTOR_SIGMA_FLOOR ?= 0.05
DOCKER_NET  := host
STAMP_DIR   := .stamps
RENDER      := bin/render.sh

# ROLE=client: kubectl usa o kubeconfig exportado pela VPS
ifneq ($(strip $(KUBECONFIG_FILE)),)
  ifeq ($(patsubst /%,/,$(KUBECONFIG_FILE)),/)
    export KUBECONFIG := $(KUBECONFIG_FILE)
  else
    export KUBECONFIG := $(CURDIR)/$(KUBECONFIG_FILE)
  endif
endif

ANALYSIS_RUN = docker run --rm --network $(DOCKER_NET) \
	-v $(CURDIR)/datasets:/datasets -v $(CURDIR)/datasets_hpa:/datasets_hpa \
	-v $(CURDIR)/results:/results -e PROMETHEUS_URL=$(PROM_URL) -e NAMESPACE=$(NAMESPACE) \
	$(ANALYSIS_IMAGE)

# =============================================================================
# GUARDS
# =============================================================================

define check_docker
	@command -v docker >/dev/null 2>&1 || { echo "✗ Docker não instalado. Rode: ./setup.sh"; exit 1; }
	@err=$$(docker info 2>&1 >/dev/null) || { \
		if echo "$$err" | grep -qi 'permission denied'; then \
			echo "✗ Usuário $$USER sem permissão no Docker. Rode: sudo usermod -aG docker $$USER e faça logout/login (não use sudo make)"; \
		else echo "✗ Docker daemon parado. Rode: sudo systemctl start docker"; fi; exit 1; }
endef

define check_kubectl
	@command -v kubectl >/dev/null 2>&1 || { echo "✗ kubectl não instalado. Rode: ./setup.sh"; exit 1; }
endef

define check_not_client
	@if [ "$(ROLE)" = "client" ]; then \
		echo "✗ 'make $@' age sobre o cluster e só roda onde ele existe (ROLE=local ou server)."; \
		echo "  Rode na VPS."; exit 1; fi
endef

define prep_dirs
	@mkdir -p datasets datasets_hpa results && chmod 777 datasets datasets_hpa results 2>/dev/null || true
endef

define check_analysis_image
	@docker image inspect $(ANALYSIS_IMAGE) >/dev/null 2>&1 || { echo "→ Imagem de análise ausente. Buildando..."; $(MAKE) -s build-analysis; }
endef

define check_datasets
	@ls datasets/*.csv >/dev/null 2>&1 || { echo "✗ Nenhum CSV em datasets/. Rode: make experiment (ou make experiment-quick)"; exit 1; }
endef

.PHONY: help setup up _up-cluster down server-up server-down ensure-cluster deploy \
        build build-analysis rebuild import-images \
        detector-config detector-deploy detector-logs online-replay check-inicio \
        ksm-deploy adapter-deploy hpa-mode hpa-status phase2-check \
        test-burst test-ramp test-shift \
        experiment experiment-quick detect k6-summary stats analyze \
        hpa-experiment hpa-analyze \
        vpn-check kubeconfig status logs clean purge selftest prep

# =============================================================================
# SETUP / CLUSTER
# =============================================================================

setup:
	@chmod +x setup.sh bin/*.sh
	@./setup.sh

$(STAMP_DIR):
	@mkdir -p $(STAMP_DIR)

## Garante: setup → cluster → imagens → deploy completo (app, monitoramento, detector, adapter, HPA)
up: | $(STAMP_DIR)
	@if [ "$(ROLE)" = "client" ]; then \
		echo "→ ROLE=client: não há cluster local; verificando a VPS pela VPN..."; \
		$(MAKE) -s vpn-check; \
	else \
		$(MAKE) -s _up-cluster; \
	fi

_up-cluster:
	$(call check_docker)
	@chmod +x setup.sh bin/*.sh && ./setup.sh
	$(call check_kubectl)
	@# ── Cluster ──
	@if k3d cluster list 2>/dev/null | grep -q "^$(CLUSTER_NAME) "; then \
		if docker port k3d-$(CLUSTER_NAME)-serverlb 2>/dev/null | grep -q ":$(APP_PORT)$$"; then \
			echo "→ Cluster já existe com portas corretas"; \
		else \
			echo "✗ Cluster existe mas com portas ERRADAS (mudou o .env?)"; \
			echo "  Rode: make down && make up"; exit 1; \
		fi; \
	else \
		echo "→ Criando cluster..."; \
		mkdir -p $(HOME)/.kube; \
		k3d cluster create --config $(K3D_CONFIG) || \
			{ echo "✗ Falha ao criar cluster. Porta em uso? Rode: make down && make up"; exit 1; }; \
		echo "→ Aguardando API server..."; \
		until kubectl cluster-info >/dev/null 2>&1; do sleep 2; done; \
		sleep 5; \
		echo "→ metrics-server..."; \
		kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null || true; \
		kubectl patch deployment metrics-server -n kube-system --type='json' \
			-p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' 2>/dev/null || true; \
	fi
	@# ── Imagens (build só se não existirem) + import no k3d ──
	@docker image inspect $(APP_IMAGE) >/dev/null 2>&1 || { echo "→ Build FastAPI..."; docker build -q -t $(APP_IMAGE) ./app; }
	@docker image inspect $(ANALYSIS_IMAGE) >/dev/null 2>&1 || { echo "→ Build Analysis..."; docker build -q -t $(ANALYSIS_IMAGE) ./scripts; }
	@$(MAKE) -s import-images
	@$(MAKE) -s deploy
	@touch $(STAMP_DIR)/up
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  Lab READY  (ROLE=$(ROLE), HPA modo $(HPA_MODE))"
	@echo "║  App:        $(APP_URL)/health"
	@echo "║  Prometheus: $(PROM_URL)"
	@echo "║  Grafana:    $(GRAFANA_URL)  (dashboards: Anomaly Detection Lab, Detector Online & HPA)"
	@echo "╚══════════════════════════════════════════════════════════════╝"

## Aplica todos os manifests (idempotente; não recria o cluster)
deploy:
	$(call check_kubectl)
	@echo "→ Aplicando manifests..."
	@kubectl apply -f k8s/namespace.yaml >/dev/null
	@kubectl apply -f k8s/monitoring/prometheus.yaml >/dev/null
	@$(RENDER) k8s/monitoring/grafana.yaml | kubectl apply -f - >/dev/null
	@kubectl apply -f k8s/monitoring/kube-state-metrics.yaml >/dev/null
	@kubectl apply -f k8s/app/deployment.yaml >/dev/null
	@$(MAKE) -s detector-deploy
	@$(MAKE) -s adapter-deploy
	@$(MAKE) -s hpa-mode HPA_MODE=$(HPA_MODE)
	@echo "→ Aguardando pods..."
	@for app in fastapi prometheus grafana kube-state-metrics online-detector prometheus-adapter; do \
		kubectl wait --for=condition=ready pod -l app=$$app -n $(NAMESPACE) --timeout=180s >/dev/null 2>&1 \
			&& echo "  ✓ $$app" || echo "  ⚠ $$app ainda não está pronto (veja: make status)"; \
	done

down:
	$(call check_not_client)
	@k3d cluster delete $(CLUSTER_NAME) 2>/dev/null || true
	@rm -f $(STAMP_DIR)/up
	@echo "✓ Destruído"

server-up: up
server-down: down

## Garante que há cluster acessível: local/server → make up; client → vpn-check
## Fixa os nós do k3d nos núcleos CLUSTER_CPUS; k6 e análise usam LOADGEN_CPUS (vazio = sem fixação)
cpu-pin:
	@if [ -n "$(CLUSTER_CPUS)" ] && [ "$(ROLE)" != "client" ]; then \
		ids=$$(docker ps -q --filter "label=k3d.cluster=$(CLUSTER_NAME)"); \
		[ -n "$$ids" ] || { echo "✗ Cluster '$(CLUSTER_NAME)' não está rodando"; exit 1; }; \
		docker update --cpuset-cpus "$(CLUSTER_CPUS)" $$ids >/dev/null \
			&& echo "→ Cluster nos núcleos $(CLUSTER_CPUS); k6 e análise nos núcleos $(or $(LOADGEN_CPUS),livres)"; fi

ensure-cluster:
	@if [ "$(ROLE)" = "client" ]; then $(MAKE) -s vpn-check; \
	elif ! k3d cluster list 2>/dev/null | grep -q "^$(CLUSTER_NAME) "; then \
		echo "→ Cluster '$(CLUSTER_NAME)' não existe. Rodando 'make up'..."; $(MAKE) -s up; fi

# =============================================================================
# BUILD
# =============================================================================

build:
	$(call check_docker)
	@echo "→ Build FastAPI..."
	@docker build -q -t $(APP_IMAGE) ./app
	@[ "$(ROLE)" = "client" ] || k3d image import $(APP_IMAGE) -c $(CLUSTER_NAME) >/dev/null 2>&1 || true
	@echo "✓ FastAPI OK"

build-analysis:
	$(call check_docker)
	@echo "→ Build Analysis (detectores, estatística, detector online)..."
	@docker build -q -t $(ANALYSIS_IMAGE) ./scripts
	@[ "$(ROLE)" = "client" ] || k3d image import $(ANALYSIS_IMAGE) -c $(CLUSTER_NAME) >/dev/null 2>&1 || true
	@echo "✓ Analysis OK"

rebuild: build build-analysis
	@[ "$(ROLE)" = "client" ] || kubectl -n $(NAMESPACE) rollout restart deploy/fastapi-app deploy/online-detector >/dev/null 2>&1 || true
	@echo "✓ Tudo rebuildado"

import-images:
	@k3d image import $(APP_IMAGE) $(ANALYSIS_IMAGE) -c $(CLUSTER_NAME) >/dev/null 2>&1 \
		&& echo "→ Imagens importadas no k3d" || echo "⚠ Falha ao importar imagens no k3d"

# =============================================================================
# FASE 2 — DETECTOR ONLINE, ADAPTER, HPA
# =============================================================================

## ConfigMap do detector a partir do .env (só as chaves do detector)
detector-config:
	@for d in $$(echo "$(DETECTOR_ALGOS)" | tr ',' ' '); do case "$$d" in EWMA|IF|LOF|DBSCAN|AE) ;; \
		*) echo "✗ DETECTOR_ALGOS: '$$d' inválido (aceitos: EWMA, IF, LOF, DBSCAN, AE)"; exit 1 ;; esac; done
	$(call check_kubectl)
	@kubectl -n $(NAMESPACE) create configmap online-detector-config \
		--from-literal=PROMETHEUS_URL=$(PROMETHEUS_INCLUSTER_URL) \
		--from-literal=NAMESPACE=$(NAMESPACE) \
		--from-literal=DETECTOR_PORT=$(DETECTOR_PORT) \
		--from-literal=DETECTOR_ALGOS=$(DETECTOR_ALGOS) \
		--from-literal=DETECTOR_STEP_SECONDS=$(DETECTOR_STEP_SECONDS) \
		--from-literal=DETECTOR_WINDOW=$(DETECTOR_WINDOW) \
		--from-literal=DETECTOR_GAP=$(DETECTOR_GAP) \
		--from-literal=DETECTOR_K_SIGMA=$(DETECTOR_K_SIGMA) \
		--from-literal=DETECTOR_SIGMA_FLOOR=$(DETECTOR_SIGMA_FLOOR) \
		--from-literal=DETECTOR_LEVEL_POINTS=$(DETECTOR_LEVEL_POINTS) \
		--from-literal=DETECTOR_AE_RETRAIN=$(DETECTOR_AE_RETRAIN) \
		--from-literal=TARGET_APP=$(TARGET_APP) \
		--dry-run=client -o yaml | kubectl apply -f - >/dev/null
	@echo "→ ConfigMap online-detector-config atualizado"

## Detector online no cluster (score dos 5 detectores no Prometheus/Grafana)
## Idempotente: o hash da configuração vai numa anotação do pod; o Kubernetes só
## recria o pod se a configuração (ou a imagem, via make rebuild) mudou.
DETECTOR_CONFIG_HASH = $(shell printf '%s' "$(PROMETHEUS_INCLUSTER_URL)|$(NAMESPACE)|$(DETECTOR_PORT)|$(DETECTOR_ALGOS)|$(DETECTOR_STEP_SECONDS)|$(DETECTOR_WINDOW)|$(DETECTOR_GAP)|$(DETECTOR_K_SIGMA)|$(DETECTOR_SIGMA_FLOOR)|$(DETECTOR_LEVEL_POINTS)|$(DETECTOR_AE_RETRAIN)|$(TARGET_APP)" | cksum | cut -d' ' -f1)
detector-deploy: detector-config
	@DETECTOR_CONFIG_HASH=$(DETECTOR_CONFIG_HASH) $(RENDER) k8s/detector/online-detector.yaml | kubectl apply -f - >/dev/null
	@echo "→ Detector online aplicado (algos: $(DETECTOR_ALGOS); config $(DETECTOR_CONFIG_HASH))"

detector-logs:
	$(call check_kubectl)
	@kubectl -n $(NAMESPACE) logs deploy/online-detector -f --tail=50

## Testa o detector online SEM cluster, reproduzindo um CSV: make online-replay CSV=datasets/burst_run1.csv
CSV ?= datasets/burst_run1.csv
online-replay:
	$(call check_analysis_image)
	@test -f "$(CSV)" || { echo "✗ $(CSV) não existe"; exit 1; }
	@mkdir -p results && chmod 777 results
	@docker run --rm -v $(CURDIR)/$(dir $(CSV)):/in:ro -v $(CURDIR)/results:/results \
		-e DETECTOR_ALGOS=$(DETECTOR_ALGOS) -e DETECTOR_WINDOW=$(DETECTOR_WINDOW) \
		-e DETECTOR_GAP=$(DETECTOR_GAP) -e DETECTOR_K_SIGMA=$(DETECTOR_K_SIGMA) -e DETECTOR_SIGMA_FLOOR=$(DETECTOR_SIGMA_FLOOR) \
		-e DETECTOR_LEVEL_POINTS=$(DETECTOR_LEVEL_POINTS) -e DETECTOR_AE_RETRAIN=$(DETECTOR_AE_RETRAIN) \
		$(ANALYSIS_IMAGE) online_detector.py --replay /in/$(notdir $(CSV)) \
		--replay-out /results/replay_$(notdir $(CSV))

## Alertas online antes da 1ª anomalia de cada CSV (falsos alarmes do início): make check-inicio DIR=datasets_hpa
DIR ?= datasets
check-inicio:
	$(call check_analysis_image)
	@ls $(DIR)/*.csv >/dev/null 2>&1 || { echo "✗ Nenhum CSV em $(DIR)/"; exit 1; }
	@docker run --rm -v $(CURDIR)/$(DIR):/in:ro $(ANALYSIS_IMAGE) check_inicio.py /in

ksm-deploy:
	$(call check_kubectl)
	@kubectl apply -f k8s/monitoring/kube-state-metrics.yaml >/dev/null && echo "→ kube-state-metrics aplicado"

## Prometheus Adapter: anomaly_level → external.metrics.k8s.io
adapter-deploy:
	$(call check_kubectl)
	@kubectl apply -f k8s/adapter/prometheus-adapter.yaml >/dev/null
	@echo "→ Prometheus Adapter aplicado"

## Troca o modo do HPA: make hpa-mode HPA_MODE=A|B|C|D
hpa-mode:
	$(call check_kubectl)
	@for d in $(HPA_B_DETECTOR) $(HPA_D_DETECTOR); do \
		echo ",$(DETECTOR_ALGOS)," | grep -q ",$$d," || { echo "✗ Detector '$$d' do HPA não está em DETECTOR_ALGOS=$(DETECTOR_ALGOS)"; exit 1; }; done
	@case "$(HPA_MODE)" in \
		A) HPA_CPU_TARGET=50 HPA_DETECTOR=- $(RENDER) k8s/hpa/hpa-cpu.yaml ;; \
		B) HPA_CPU_TARGET=50 HPA_DETECTOR=$(HPA_B_DETECTOR) $(RENDER) k8s/hpa/hpa-anomaly.yaml ;; \
		C) HPA_CPU_TARGET=$(HPA_C_CPU_TARGET) HPA_DETECTOR=- $(RENDER) k8s/hpa/hpa-cpu.yaml ;; \
		D) HPA_CPU_TARGET=50 HPA_DETECTOR=$(HPA_D_DETECTOR) $(RENDER) k8s/hpa/hpa-anomaly.yaml ;; \
		*) echo "✗ HPA_MODE inválido: $(HPA_MODE) (use A, B, C ou D)" >&2; exit 1 ;; \
	esac | kubectl apply -f - >/dev/null
	@echo "→ HPA no modo $(HPA_MODE)"

hpa-status:
	$(call check_kubectl)
	@kubectl -n $(NAMESPACE) get hpa fastapi-hpa -o wide
	@echo ""; kubectl -n $(NAMESPACE) get hpa fastapi-hpa -o jsonpath='{.metadata.labels.hpa-mode}{"\n"}' | sed 's/^/modo: /'

## A métrica de anomalia chegou ao HPA?
phase2-check:
	$(call check_kubectl)
	@echo "── anomaly_level via external.metrics.k8s.io ──"
	@kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/$(NAMESPACE)/anomaly_level" 2>&1 | head -c 800; echo
	@echo ""; echo "── HPA ──"
	@kubectl -n $(NAMESPACE) describe hpa fastapi-hpa | sed -n '/Metrics:/,/Events:/p'

# =============================================================================
# K6 — testes avulsos (garantem cluster acessível antes)
# =============================================================================

define k6_single
	@$(MAKE) -s ensure-cluster
	@mkdir -p results/k6 && chmod 777 results results/k6 2>/dev/null || true
	@echo "→ [K6] $(1) → $(APP_URL)"
	@docker run --rm --network $(DOCKER_NET) \
		-v $(CURDIR)/k6-scripts:/scripts:ro -v $(CURDIR)/results:/results \
		-e BASE_URL=$(APP_URL) -e SUMMARY_FILE=/results/k6/avulso_$(1)_$$(date +%s).json \
		$(K6_IMAGE) run --summary-trend-stats="avg,min,med,max,p(90),p(95),p(99)" /scripts/$(2) || true
endef

test-burst:
	$(call k6_single,burst,burst-anomaly.js)
test-ramp:
	$(call k6_single,rampup,rampup-irregular.js)
test-shift:
	$(call k6_single,shift,load-shifting.js)

# =============================================================================
# FASE 1 — EXPERIMENTO + ANÁLISE
# =============================================================================

## REPS repetições × 3 cenários (ordem aleatória, retomável) → datasets/ + results/k6/ → análise
experiment:
	@$(MAKE) -s ensure-cluster
	@$(MAKE) -s cpu-pin
	$(call check_analysis_image)
	@bin/experiment.sh phase1
	@$(MAKE) -s analyze

## 1 repetição do burst (~14 min) para testar o pipeline
experiment-quick:
	@$(MAKE) -s experiment REPS=1 SCENARIOS=burst

client-experiment: experiment

## 5 detectores sobre datasets/ → results/detection_results.csv
detect:
	$(call check_datasets)
	$(call check_analysis_image)
	$(call prep_dirs)
	@$(ANALYSIS_RUN) detectors.py --input /datasets/ --output /results/ --impute $(IMPUTE)

k6-summary:
	$(call check_analysis_image)
	$(call prep_dirs)
	@ls results/k6/*_run*.json >/dev/null 2>&1 || { echo "✗ Nenhum summary em results/k6/ (rode make experiment)"; exit 1; }
	@$(ANALYSIS_RUN) k6_summary.py --input /results/k6 --output /results/k6_summary.csv

## IC da média (TLC) + t de Student → results/stats/phase1/
stats:
	$(call check_analysis_image)
	$(call prep_dirs)
	@test -f results/detection_results.csv || $(MAKE) -s detect
	@K6=""; [ -f results/k6_summary.csv ] && K6="--k6 /results/k6_summary.csv"; \
		$(ANALYSIS_RUN) stats_tlc.py phase1 --detections /results/detection_results.csv $$K6 --out /results/stats/phase1

analyze: detect
	@-$(MAKE) -s k6-summary
	@$(MAKE) -s stats

# =============================================================================
# FASE 3 — HPA REATIVO × PROATIVO
# =============================================================================

## HPA_MODES × cenários × REPS (ordem aleatória, retomável) → results/hpa/hpa_results.csv
hpa-experiment:
	@$(MAKE) -s ensure-cluster
	@$(MAKE) -s cpu-pin
	$(call check_analysis_image)
	@bin/experiment.sh phase3
	@$(MAKE) -s hpa-analyze

hpa-analyze:
	$(call check_analysis_image)
	$(call prep_dirs)
	@test -f results/hpa/hpa_results.csv || { echo "✗ results/hpa/hpa_results.csv não existe (rode make hpa-experiment)"; exit 1; }
	@-$(ANALYSIS_RUN) k6_summary.py --input /results/hpa/k6 --output /results/hpa/k6_summary.csv
	@$(ANALYSIS_RUN) stats_tlc.py phase3 --hpa /results/hpa/hpa_results.csv --k6 /results/hpa/k6_summary.csv --out /results/stats/phase3

# =============================================================================
# VPS + VPN
# =============================================================================

## (notebook) Testa app, Prometheus, Grafana, API do K8s e detector pela VPN
vpn-check:
	@ok=1; \
	chk() { if curl -fsS -m 5 -o /dev/null "$$2"; then echo "  ✓ $$1  $$2"; else echo "  ✗ $$1  $$2"; ok=0; fi; }; \
	echo "→ Verificando $(CLUSTER_HOST) ..."; \
	chk "App       " "$(APP_URL)/health"; \
	chk "Prometheus" "$(PROM_URL)/-/ready"; \
	chk "Grafana   " "$(GRAFANA_URL)/api/health"; \
	if curl -fsS -m 5 -G "$(PROM_URL)/api/v1/query" --data-urlencode 'query=count(anomaly_score)' 2>/dev/null | grep -q '"value"'; then \
		echo "  ✓ Detector online sendo coletado pelo Prometheus"; else echo "  ⚠ Detector online ainda não aparece no Prometheus"; fi; \
	if command -v kubectl >/dev/null 2>&1 && kubectl get nodes >/dev/null 2>&1; then \
		echo "  ✓ API do Kubernetes (kubectl) — $$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"; \
	else echo "  ✗ kubectl não alcança o cluster (KUBECONFIG_FILE=$(KUBECONFIG_FILE)). Necessário para a Fase 3."; ok=0; fi; \
	[ $$ok = 1 ] && echo "✓ VPS acessível" || { echo "✗ Verifique a VPN, o .env (CLUSTER_HOST/BIND_ADDR) e 'make status' na VPS"; exit 1; }

## (VPS) Exporta kubeconfig para o notebook usar pela VPN → kubeconfig-vpn.yaml
kubeconfig:
	$(call check_not_client)
	@command -v k3d >/dev/null 2>&1 || { echo "✗ k3d não instalado nesta máquina. Rode primeiro: make server-up"; exit 1; }
	@k3d cluster list 2>/dev/null | grep -q "^$(CLUSTER_NAME) " \
		|| { echo "✗ Cluster '$(CLUSTER_NAME)' não existe nesta máquina. Rode primeiro: make server-up"; exit 1; }
	@k3d kubeconfig get $(CLUSTER_NAME) \
		| sed -E "s#server: https://[^:]+:[0-9]+#server: https://$(CLUSTER_HOST):$(KUBE_API_PORT)#" > kubeconfig-vpn.yaml.tmp \
		&& grep -q "server: https://$(CLUSTER_HOST):$(KUBE_API_PORT)" kubeconfig-vpn.yaml.tmp \
		|| { rm -f kubeconfig-vpn.yaml.tmp; echo "✗ Não foi possível gerar o kubeconfig (veja: k3d kubeconfig get $(CLUSTER_NAME))"; exit 1; }
	@mv kubeconfig-vpn.yaml.tmp kubeconfig-vpn.yaml && chmod 600 kubeconfig-vpn.yaml
	@echo "✓ kubeconfig-vpn.yaml (server: https://$(CLUSTER_HOST):$(KUBE_API_PORT))"
	@echo "  Copie para o notebook (ex.: scp) e defina KUBECONFIG_FILE=kubeconfig-vpn.yaml no .env de lá."

# =============================================================================
# UTIL
# =============================================================================

## Autoteste do código de análise (sem cluster): detectores, detector online, IC, métricas do HPA
selftest:
	$(call check_analysis_image)
	@docker run --rm $(ANALYSIS_IMAGE) selftest.py

status:
	$(call check_kubectl)
	@kubectl get pods -n $(NAMESPACE) -o wide
	@echo ""; kubectl get hpa -n $(NAMESPACE) -L hpa-mode
	@echo ""; kubectl top pods -n $(NAMESPACE) 2>/dev/null || true

logs:
	$(call check_kubectl)
	@kubectl logs -n $(NAMESPACE) -l app=fastapi -f --tail=50

## Zera TUDO do lab nesta máquina (só do lab): cluster, imagens, dados gerados e arquivos gerados.
## Não usa "docker system prune": outros containers/imagens da máquina (ex.: serviços da VPS) ficam intactos.
## Preserva: código, .env, datasets_qualificacao/, results_qualificacao/.  Sem perguntar: make purge CONFIRM=yes
purge:
	@echo "Isto vai remover DESTA máquina:"
	@echo "  • cluster k3d '$(CLUSTER_NAME)' (se existir)"
	@echo "  • imagens: $(APP_IMAGE), $(ANALYSIS_IMAGE), $(K6_IMAGE), rancher/k3s, ghcr.io/k3d-io/*"
	@echo "  • datasets/, datasets_hpa/, results/, .stamps/, k3d-config.yaml, kubeconfig-vpn.yaml"
	@echo "  • binários /usr/local/bin/k3d e /usr/local/bin/kubectl (instalados pelo setup.sh)"
	@echo "Preserva: código, .env, datasets_qualificacao/, results_qualificacao/ e qualquer outro container/imagem."
	@if [ "$(CONFIRM)" != "yes" ]; then \
		read -r -p "Digite 'sim' para continuar: " ans; [ "$$ans" = "sim" ] || { echo "Cancelado."; exit 1; }; fi
	@if [ "$(ROLE)" != "client" ] && command -v k3d >/dev/null 2>&1; then \
		k3d cluster delete $(CLUSTER_NAME) >/dev/null 2>&1 && echo "✓ cluster removido" || echo "• sem cluster"; fi
	@for img in $(APP_IMAGE) $(ANALYSIS_IMAGE) $(K6_IMAGE); do \
		docker image rm -f "$$img" >/dev/null 2>&1 && echo "✓ imagem $$img" || true; done
	@docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
		| grep -E '^(rancher/k3s|ghcr\.io/k3d-io/)' | xargs -r docker image rm -f >/dev/null 2>&1 \
		&& echo "✓ imagens do k3d/k3s" || true
	@rm -rf datasets datasets_hpa results $(STAMP_DIR) k3d-config.yaml kubeconfig-vpn.yaml
	@mkdir -p datasets results && touch datasets/.gitkeep results/.gitkeep
	@for bin in /usr/local/bin/k3d /usr/local/bin/kubectl; do \
		[ -e "$$bin" ] || continue; \
		{ rm -f "$$bin" 2>/dev/null || sudo rm -f "$$bin"; } && echo "✓ binário $$bin"; done
	@echo "✓ Lab zerado. Para começar de novo: ./setup.sh && make up"

## Remove dados GERADOS (datasets/, datasets_hpa/, results/). Não toca nos dados da qualificação.
clean:
	@rm -rf results datasets datasets_hpa $(STAMP_DIR)
	@echo "✓ Limpo (datasets_qualificacao/ e results_qualificacao/ preservados)"

help:
	@echo ""
	@echo "  ROLE=$(ROLE)  CLUSTER_HOST=$(CLUSTER_HOST)  REPS=$(REPS)  HPA_MODE=$(HPA_MODE)"
	@echo "  Qualquer alvo resolve suas dependências. Ordem não importa."
	@echo ""
	@echo "  Cluster (local/server)"
	@echo "    make up                 cluster + imagens + app + Prometheus + Grafana + detector online + adapter + HPA"
	@echo "    make deploy             reaplica só os manifests"
	@echo "    make status | logs      pods, HPA (com modo) e consumo"
	@echo "    make down               destrói o cluster"
	@echo ""
	@echo "  Fase 1 (comparação dos 5 detectores)"
	@echo "    make experiment         REPS × 3 cenários, ordem aleatória, retomável + análise"
	@echo "    make experiment-quick   1 rodada burst (~14 min)"
	@echo "    make detect | stats     detectores sobre datasets/ | IC + t de Student"
	@echo ""
	@echo "  Fase 2 (detector online)"
	@echo "    make online-replay CSV=datasets_qualificacao/burst_run1.csv   testa sem cluster"
	@echo "    make check-inicio DIR=datasets_hpa   alertas online antes da 1ª anomalia (falsos alarmes)"
	@echo "    make detector-deploy | detector-logs"
	@echo "    make hpa-mode HPA_MODE=B | hpa-status | phase2-check"
	@echo ""
	@echo "  Fase 3 (HPA A × B × C)"
	@echo "    make hpa-experiment     HPA_MODES × 3 cenários × REPS + análise"
	@echo ""
	@echo "  make selftest            autoteste do código (sem cluster)"
	@echo "  make clean | purge       apaga dados gerados | zera o lab inteiro (cluster+imagens+dados)"
	@echo ""
	@echo "  VPS + notebook (VPN)"
	@echo "    VPS:      ROLE=server → make server-up && make kubeconfig"
	@echo "    Notebook: ROLE=client → make vpn-check && make experiment && make hpa-experiment"
	@echo ""
