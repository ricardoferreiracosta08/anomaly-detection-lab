#!/bin/bash
# =============================================================================
# setup.sh — Verifica/instala pré-requisitos + gera configs a partir do .env
# Roda uma vez. Depois é só make up.
# =============================================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Anomaly Detection Lab — Setup               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Carregar .env ──────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    fail ".env não encontrado. Crie a partir do .env.example"
    exit 1
fi
set -a; source .env; set +a
ok ".env carregado (CLUSTER_HOST=$CLUSTER_HOST, APP_PORT=$APP_PORT)"

# ── 0. Kubeconfig ──────────────────────────────────────────────────────────
echo "→ Garantindo diretório kubeconfig..."
mkdir -p "$HOME/.kube"
if [ ! -w "$HOME/.kube" ]; then
    sudo chown -R "$USER" "$HOME/.kube"
fi
ok "~/.kube pronto (owner=$USER)"

# ── 1. Docker ──────────────────────────────────────────────────────────────
echo ""
echo "→ Verificando pré-requisitos..."

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    ok "Docker $DOCKER_VER instalado"
    if ! docker info &>/dev/null; then
        warn "Docker daemon não está rodando. Inicie com: sudo systemctl start docker"
        exit 1
    fi
else
    fail "Docker não encontrado"
    echo "    Instalando..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    ok "Docker instalado. FAÇA LOGOUT e login novamente para o grupo docker funcionar."
    exit 1
fi

# ── 2. k3d ─────────────────────────────────────────────────────────────────
if command -v k3d &>/dev/null; then
    K3D_VER=$(k3d version | grep -oP 'v\d+\.\d+\.\d+' | head -1)
    ok "k3d $K3D_VER instalado"
else
    warn "k3d não encontrado. Instalando..."
    curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
    ok "k3d instalado"
fi

# ── 3. kubectl ─────────────────────────────────────────────────────────────
if command -v kubectl &>/dev/null; then
    KUBE_VER=$(kubectl version --client -o json 2>/dev/null | grep -oP '"gitVersion":\s*"\K[^"]+' | head -1)
    ok "kubectl $KUBE_VER instalado"
else
    warn "kubectl não encontrado. Instalando..."
    KUBE_STABLE=$(curl -Ls https://dl.k8s.io/release/stable.txt)
    curl -LO "https://dl.k8s.io/release/${KUBE_STABLE}/bin/linux/amd64/kubectl"
    chmod +x kubectl
    sudo mv kubectl /usr/local/bin/
    ok "kubectl instalado"
fi

# ── 4. Gerar k3d-config.yaml a partir do .env ─────────────────────────────
echo ""
echo "→ Gerando k3d-config.yaml com portas do .env..."
echo "  APP_PORT=$APP_PORT  PROM_PORT=$PROM_PORT  GRAFANA_PORT=$GRAFANA_PORT"

cat > k3d-config.yaml <<EOF
# GERADO por setup.sh a partir do .env — NÃO EDITAR MANUALMENTE
apiVersion: k3d.io/v1alpha5
kind: Simple

metadata:
  name: ${CLUSTER_NAME}

servers: 1
agents: 2

image: rancher/k3s:v1.30.4-k3s1

# Mapeia portas do HOST (.env) → NodePorts fixos dentro do K3D
ports:
  - port: "${APP_PORT}:30080"
    nodeFilters: [servers:0]
  - port: "${PROM_PORT}:30090"
    nodeFilters: [servers:0]
  - port: "${GRAFANA_PORT}:30030"
    nodeFilters: [servers:0]

options:
  k3d:
    wait: true
    timeout: "120s"
  k3s:
    extraArgs:
      - arg: "--disable=traefik"
        nodeFilters: [servers:*]
      - arg: "--service-node-port-range=30000-32767"
        nodeFilters: [servers:*]
  kubeconfig:
    updateDefaultKubeconfig: true
    switchCurrentContext: true
EOF

ok "k3d-config.yaml gerado"

# ── 5. Atualizar NodePort nos manifests K8s ────────────────────────────────
echo ""
echo "→ Verificando NodePorts nos manifests K8s..."
ok "NodePorts fixos: App=30080, Prometheus=30090, Grafana=30030"
ok "Portas externas (do .env): App=$APP_PORT, Prom=$PROM_PORT, Grafana=$GRAFANA_PORT"

# ── Resumo ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Setup completo!                              ║"
echo "║                                              ║"
echo "║  Próximo passo:                               ║"
echo "║    make up                                    ║"
echo "╚══════════════════════════════════════════════╝"
