#!/usr/bin/env bash
#
# Lance le serveur du MisteR Dashboard détaché de la session courante (setsid nohup), pour qu'il
# survive au terminal ou à la session Claude Code qui l'a démarré.
#
# Usage : scripts/mr-dashboard/start.sh [--port 9100]
#   Les arguments sont transmis tels quels à server.py.
#
# Le serveur servi est celui du dépôt (ou du worktree) où vit ce script, quel que soit le
# répertoire courant.
#
# Variables d'environnement :
#   MR_DASHBOARD_LOG   fichier journal   (défaut : ~/.local/state/mr-dashboard.log)

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_file="${MR_DASHBOARD_LOG:-$HOME/.local/state/mr-dashboard.log}"

port=8765
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
        --port) port="${args[i + 1]:-$port}" ;;
        --port=*) port="${args[i]#--port=}" ;;
    esac
done
url="http://localhost:${port}/"

if running="$(pgrep -af mr-dashboard/server.py)"; then
    echo "Déjà lancé :"
    echo "$running"
    echo "$url"
    exit 0
fi

if [[ -z "${SONAR_TOKEN:-}" ]]; then
    echo "⚠️  SONAR_TOKEN absent : les pastilles Sonar resteront grises." >&2
fi

mkdir -p "$(dirname "$log_file")"
setsid nohup python3 "$script_dir/server.py" "$@" > "$log_file" 2>&1 < /dev/null &
disown

for _ in $(seq 1 20); do
    if [[ "$(curl -s -o /dev/null -w '%{http_code}' "$url")" == "200" ]]; then
        echo "MisteR Dashboard lancé : $url"
        echo "Journal : $log_file — arrêt : $script_dir/stop.sh"
        exit 0
    fi
    sleep 0.5
done

echo "Le serveur ne répond pas en 200 sur $url après 10 s. Journal :" >&2
tail -n 20 "$log_file" >&2
exit 1
