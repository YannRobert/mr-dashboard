#!/usr/bin/env bash
#
# Arrête le serveur du MisteR Dashboard lancé par start.sh.
#
# Usage : scripts/mr-dashboard/stop.sh [profil]
#   profil   celui passé à start.sh ; sans argument, arrête tous les profils lancés

set -euo pipefail

state_dir="$HOME/.local/state"

stop_profile() {
    local profile="$1"
    local pid_file="$state_dir/mr-dashboard-$profile.pid"
    local pid
    if [[ ! -f "$pid_file" ]] || ! kill -0 "$(cat "$pid_file")" 2> /dev/null; then
        rm -f "$pid_file"
        echo "MisteR Dashboard ($profile) non lancé."
        return
    fi
    pid="$(cat "$pid_file")"
    kill "$pid"
    for _ in $(seq 1 10); do
        if ! kill -0 "$pid" 2> /dev/null; then
            rm -f "$pid_file"
            echo "MisteR Dashboard ($profile) arrêté."
            return
        fi
        sleep 0.5
    done
    echo "MisteR Dashboard ($profile) ne s'est pas arrêté après 5 s : arrêt forcé." >&2
    kill -9 "$pid"
    rm -f "$pid_file"
}

if [[ $# -gt 0 ]]; then
    stop_profile "$1"
    exit 0
fi

shopt -s nullglob
pid_files=("$state_dir"/mr-dashboard-*.pid)
if [[ ${#pid_files[@]} -eq 0 ]]; then
    echo "Aucun MisteR Dashboard lancé."
    exit 0
fi
for pid_file in "${pid_files[@]}"; do
    profile="${pid_file##*/mr-dashboard-}"
    stop_profile "${profile%.pid}"
done
