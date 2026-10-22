#!/usr/bin/env bash
#
# Stops the MisteR Dashboard server started by start.sh.
#
# Usage: stop.sh [profile]
#   profile  the name given to start.sh (a profile path is accepted too); without argument, stops
#            every running profile

set -euo pipefail

state_dir="$HOME/.local/state"

stop_profile() {
    local profile="$1"
    local pid_file="$state_dir/mr-dashboard-$profile.pid"
    local pid
    if [[ ! -f "$pid_file" ]] || ! kill -0 "$(cat "$pid_file")" 2> /dev/null; then
        rm -f "$pid_file"
        echo "MisteR Dashboard ($profile) not running."
        return
    fi
    pid="$(cat "$pid_file")"
    kill "$pid"
    for _ in $(seq 1 10); do
        if ! kill -0 "$pid" 2> /dev/null; then
            rm -f "$pid_file"
            echo "MisteR Dashboard ($profile) stopped."
            return
        fi
        sleep 0.5
    done
    echo "MisteR Dashboard ($profile) did not stop after 5 s: killing it." >&2
    kill -9 "$pid"
    rm -f "$pid_file"
}

if [[ $# -gt 0 ]]; then
    stop_profile "$(basename "$1" .conf)"
    exit 0
fi

shopt -s nullglob
pid_files=("$state_dir"/mr-dashboard-*.pid)
if [[ ${#pid_files[@]} -eq 0 ]]; then
    echo "No MisteR Dashboard running."
    exit 0
fi
for pid_file in "${pid_files[@]}"; do
    profile="${pid_file##*/mr-dashboard-}"
    stop_profile "${profile%.pid}"
done
