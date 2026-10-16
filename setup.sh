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
ROLE="${ROLE:-local}"
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
KUBE_API_PORT="${KUBE_API_PORT:-6550}"
ok ".env carregado (ROLE=$ROLE, CLUSTER_HOST=$CLUSTER_HOST, BIND_ADDR=$BIND_ADDR)"
case "$ROLE" in local|server|client) ;; *) fail "ROLE inválido: $ROLE (use local|server|client)"; exit 1 ;; esac
if [ "$ROLE" = "server" ] && [ "$BIND_ADDR" = "0.0.0.0" ]; then
    warn "BIND_ADDR=0.0.0.0 na VPS expõe app, Prometheus, Grafana e API do K8s na internet."
    warn "Use o IP da VPS na VPN (ex.: 10.0.0.1)."
fi

# ── 0. Kubeconfig ──────────────────────────────────────────────────────────
echo "→ Garantindo diretório kubeconfig..."
mkdir -p "$HOME/.kube"
if [ ! -w "$HOME/.kube" ]; then
    sudo chown -R "$USER" "$HOME/.kube"
fi
ok "$HOME/.kube pronto (owner=$USER)"

# ── 1. Docker ──────────────────────────────────────────────────────────────
echo ""
echo "→ Verificando pré-requisitos..."

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    ok "Docker $DOCKER_VER instalado"
    if ! DOCKER_ERR=$(docker info 2>&1 >/dev/null); then
        if echo "$DOCKER_ERR" | grep -qi 'permission denied'; then
            fail "Usuário $USER sem permissão no Docker (só funciona com sudo)."
            echo "    Rode: sudo usermod -aG docker $USER   e depois faça logout/login (ou: newgrp docker)"
            echo "    Não rode o setup.sh nem o make com sudo: os arquivos ficariam com dono root."
        else
            warn "Docker daemon não está rodando. Inicie com: sudo systemctl start docker"
        fi
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

# k3d e kubectl são instalados em /usr/local/bin; no AlmaLinux o root às vezes não tem essa pasta no PATH
case ":$PATH:" in *:/usr/local/bin:*) ;; *)
    export PATH="$PATH:/usr/local/bin"
    warn "/usr/local/bin não estava no PATH. Para o make achar o k3d, rode uma vez:"
    echo "      echo 'export PATH=\$PATH:/usr/local/bin' >> ~/.bashrc && source ~/.bashrc" ;;
esac

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
if [ "$ROLE" = "client" ]; then
    echo ""
    ok "ROLE=client: nenhum cluster local; o cluster roda na VPS ($CLUSTER_HOST)"
    [ -n "${KUBECONFIG_FILE:-}" ] && [ -f "$KUBECONFIG_FILE" ] \
        && ok "kubeconfig da VPS: $KUBECONFIG_FILE" \
        || warn "KUBECONFIG_FILE não encontrado. Na VPS rode 'make kubeconfig' e copie o arquivo para cá."
    echo ""
    echo "  Próximo passo: make vpn-check"
    exit 0
fi
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

# API do Kubernetes: publicada só em BIND_ADDR; certificado válido para CLUSTER_HOST
# (permite kubectl do notebook pela VPN com o kubeconfig exportado por 'make kubeconfig')
kubeAPI:
  host: "${CLUSTER_HOST}"
  hostIP: "${BIND_ADDR}"
  hostPort: "${KUBE_API_PORT}"

# Mapeia portas do HOST (.env) → NodePorts fixos dentro do K3D, só em BIND_ADDR
ports:
  - port: "${BIND_ADDR}:${APP_PORT}:30080"
    nodeFilters: [servers:0]
  - port: "${BIND_ADDR}:${PROM_PORT}:30090"
    nodeFilters: [servers:0]
  - port: "${BIND_ADDR}:${GRAFANA_PORT}:30030"
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
      - arg: "--tls-san=${CLUSTER_HOST}"
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
ok "Portas externas (do .env, em $BIND_ADDR): App=$APP_PORT, Prom=$PROM_PORT, Grafana=$GRAFANA_PORT, API=$KUBE_API_PORT"

# ── Resumo ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Setup completo!                              ║"
echo "║                                              ║"
echo "║  Próximo passo:                               ║"
echo "║    make up                                    ║"
echo "╚══════════════════════════════════════════════╝"
