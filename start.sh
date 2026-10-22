#!/usr/bin/env bash
#
# Starts the MisteR Dashboard server detached from the current session (setsid nohup), so that it
# outlives the terminal that started it.
#
# Usage: start.sh <profile> [server.py options…]
#   profile  path to a profile file, or the name of one in $MR_DASHBOARD_PROFILES
#            (default: ~/.config/mr-dashboard/profiles), without its .conf extension; each profile
#            runs alongside the others on its own port (see profile.example.conf)
#   options  passed as is to server.py, after those of the profile (they win)
#
# State files, one set per profile, in ~/.local/state:
#   mr-dashboard-<profile>.log   server log
#   mr-dashboard-<profile>.pid   PID, read by stop.sh

set -euo pipefail

dashboard_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
profiles_dir="${MR_DASHBOARD_PROFILES:-$HOME/.config/mr-dashboard/profiles}"
state_dir="$HOME/.local/state"

if [[ $# -eq 0 || "$1" == -* ]]; then
    echo "Usage: $0 <profile> [server.py options…] (see profile.example.conf)" >&2
    exit 1
fi
if [[ "$1" == */* || "$1" == *.conf ]]; then
    profile_file="$1"
else
    profile_file="$profiles_dir/$1.conf"
fi
shift
if [[ ! -f "$profile_file" ]]; then
    echo "Unknown profile: no $profile_file." >&2
    exit 1
fi
profile="$(basename "$profile_file" .conf)"

PORT= GITLAB_HOST= GITLAB_PROJECT= SONAR_ENABLED= SONAR_HOST= SONAR_PROJECT= SONAR_JOB= PIT_ENABLED= PIT_JOB= PIT_MARKER= PIPELINE_BRANCH= TARGET_BRANCH= REPO_DIR= GIT_FETCH_INTERVAL=
# shellcheck source=profile.example.conf
source "$profile_file"

for switch in SONAR_ENABLED PIT_ENABLED; do
    if [[ "${!switch}" != true && "${!switch}" != false ]]; then
        echo "$switch must be true or false in $profile_file (value: '${!switch}')." >&2
        exit 1
    fi
done

args=()
[[ -n "$PORT" ]] && args+=(--port "$PORT")
[[ -n "$GITLAB_HOST" ]] && args+=(--gitlab-host "$GITLAB_HOST")
[[ -n "$GITLAB_PROJECT" ]] && args+=(--gitlab-project "$GITLAB_PROJECT")
if [[ "$SONAR_ENABLED" == false ]]; then
    args+=(--no-sonar)
else
    [[ -n "$SONAR_HOST" ]] && args+=(--sonar-host "$SONAR_HOST")
    [[ -n "$SONAR_PROJECT" ]] && args+=(--sonar-project "$SONAR_PROJECT")
    [[ -n "$SONAR_JOB" ]] && args+=(--sonar-job "$SONAR_JOB")
fi
if [[ "$PIT_ENABLED" == false ]]; then
    args+=(--no-pit)
else
    [[ -n "$PIT_JOB" ]] && args+=(--pit-job "$PIT_JOB")
    [[ -n "$PIT_MARKER" ]] && args+=(--pit-marker "$PIT_MARKER")
fi
[[ -n "$PIPELINE_BRANCH" ]] && args+=(--pipeline-branch "$PIPELINE_BRANCH")
[[ -n "$TARGET_BRANCH" ]] && args+=(--target-branch "$TARGET_BRANCH")
[[ -n "$REPO_DIR" ]] && args+=(--repo-dir "${REPO_DIR/#\~/$HOME}")
[[ -n "$GIT_FETCH_INTERVAL" ]] && args+=(--git-fetch-interval "$GIT_FETCH_INTERVAL")
args+=("$@")

# Port actually used: the last occurrence wins, as in argparse.
port=8765
for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
        --port) port="${args[i + 1]:-$port}" ;;
        --port=*) port="${args[i]#--port=}" ;;
    esac
done
url="http://localhost:${port}/"
log_file="$state_dir/mr-dashboard-$profile.log"
pid_file="$state_dir/mr-dashboard-$profile.pid"

if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2> /dev/null; then
    echo "Profile $profile already running (PID $(cat "$pid_file")): $url"
    exit 0
fi
# Checked with ss rather than curl: under WSL, a connection to a free port is not refused, it hangs.
if [[ -n "$(ss -Hltn "sport = :$port")" ]]; then
    echo "Port $port is already taken by another process: choose another PORT in $profile_file." >&2
    exit 1
fi

if [[ "$SONAR_ENABLED" == true && -z "${SONAR_TOKEN:-}" ]]; then
    echo "⚠️  SONAR_TOKEN missing: Sonar badges will stay grey." >&2
fi

mkdir -p "$state_dir"
setsid nohup python3 "$dashboard_dir/mr_dashboard/server.py" "${args[@]}" > "$log_file" 2>&1 < /dev/null &
echo $! > "$pid_file"
disown

for _ in $(seq 1 20); do
    if [[ "$(curl -s --max-time 1 -o /dev/null -w '%{http_code}' "$url")" == "200" ]]; then
        echo "MisteR Dashboard ($profile) started: $url"
        echo "Log: $log_file — stop: $dashboard_dir/stop.sh $profile"
        exit 0
    fi
    sleep 0.5
done

echo "The server does not answer 200 on $url after 10 s. Log:" >&2
tail -n 20 "$log_file" >&2
exit 1
