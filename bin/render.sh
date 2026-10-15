#!/usr/bin/env bash
# =============================================================================
# render.sh ARQUIVO — substitui ${VAR} pelas variáveis de ambiente (vindas do .env
# via Makefile). Falha se alguma variável referenciada não estiver definida.
# Sem envsubst/helm: nada extra no host.
# =============================================================================
set -euo pipefail
[ $# -eq 1 ] && [ -f "$1" ] || { echo "uso: $0 arquivo.yaml" >&2; exit 2; }
content=$(<"$1")
while [[ $content =~ \$\{([A-Za-z_][A-Za-z0-9_]*)\} ]]; do
    name=${BASH_REMATCH[1]}
    if [ -z "${!name+x}" ]; then
        echo "render.sh: variável \${$name} usada em $1 não está definida no .env" >&2
        exit 1
    fi
    value=${!name}
    content=${content//"\${$name}"/$value}
done
printf '%s\n' "$content"
