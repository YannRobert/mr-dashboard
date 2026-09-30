#!/usr/bin/env bash
#
# Arrête le serveur du MisteR Dashboard lancé par start.sh.
#
# Usage : scripts/mr-dashboard/stop.sh

set -euo pipefail

if ! pgrep -f mr-dashboard/server.py > /dev/null; then
    echo "MisteR Dashboard non lancé."
    exit 0
fi

pkill -f mr-dashboard/server.py

for _ in $(seq 1 10); do
    if ! pgrep -f mr-dashboard/server.py > /dev/null; then
        echo "MisteR Dashboard arrêté."
        exit 0
    fi
    sleep 0.5
done

echo "Le serveur ne s'est pas arrêté après 5 s : arrêt forcé." >&2
pkill -9 -f mr-dashboard/server.py
