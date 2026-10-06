#!/usr/bin/env bash
#
# Lance le serveur du MisteR Dashboard détaché de la session courante (setsid nohup), pour qu'il
# survive au terminal ou à la session Claude Code qui l'a démarré.
#
# Usage : scripts/mr-dashboard/start.sh [profil] [options de server.py…]
#   profil   nom d'un fichier de profiles/ sans son extension (défaut : back) — projet GitLab, clé
#            Sonar, port… ; chaque profil tourne en parallèle des autres sur son propre port
#   options  transmises telles quelles à server.py, après celles du profil (elles l'emportent)
#
# Le serveur servi est celui du dépôt (ou du worktree) où vit ce script, quel que soit le
# répertoire courant.
#
# Fichiers d'état, un jeu par profil, dans ~/.local/state :
#   mr-dashboard-<profil>.log   journal du serveur
#   mr-dashboard-<profil>.pid   PID, lu par stop.sh

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
state_dir="$HOME/.local/state"

profile=back
if [[ $# -gt 0 && "$1" != -* ]]; then
    profile="$1"
    shift
fi
profile_file="$script_dir/profiles/$profile.conf"
if [[ ! -f "$profile_file" ]]; then
    echo "Profil inconnu : $profile (aucun $profile_file)." >&2
    echo "Profils disponibles : $(cd "$script_dir/profiles" && ls -- *.conf | sed 's/\.conf$//' | xargs)" >&2
    exit 1
fi

PORT= GITLAB_PROJECT= SONAR_ENABLED= SONAR_PROJECT= SONAR_JOB= PIT_ENABLED= PIT_JOB= PIT_MARKER= PIPELINE_BRANCH= TARGET_BRANCH= REPO_DIR= GIT_FETCH_INTERVAL=
# shellcheck source=profiles/back.conf
source "$profile_file"

for switch in SONAR_ENABLED PIT_ENABLED; do
    if [[ "${!switch}" != true && "${!switch}" != false ]]; then
        echo "$switch doit valoir true ou false dans $profile_file (valeur : '${!switch}')." >&2
        exit 1
    fi
done

args=()
[[ -n "$PORT" ]] && args+=(--port "$PORT")
[[ -n "$GITLAB_PROJECT" ]] && args+=(--gitlab-project "$GITLAB_PROJECT")
if [[ "$SONAR_ENABLED" == false ]]; then
    args+=(--no-sonar)
else
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

# Port réellement utilisé : la dernière occurrence l'emporte, comme dans argparse.
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
    echo "Profil $profile déjà lancé (PID $(cat "$pid_file")) : $url"
    exit 0
fi
# Test par ss et non par curl : sous WSL, une connexion à un port libre n'est pas refusée, elle
# reste en attente.
if [[ -n "$(ss -Hltn "sport = :$port")" ]]; then
    echo "Le port $port est déjà pris par un autre process : choisir un autre PORT dans $profile_file." >&2
    exit 1
fi

if [[ "$SONAR_ENABLED" == true && -z "${SONAR_TOKEN:-}" ]]; then
    echo "⚠️  SONAR_TOKEN absent : les pastilles Sonar resteront grises." >&2
fi

mkdir -p "$state_dir"
setsid nohup python3 "$script_dir/server.py" "${args[@]}" > "$log_file" 2>&1 < /dev/null &
echo $! > "$pid_file"
disown

for _ in $(seq 1 20); do
    if [[ "$(curl -s --max-time 1 -o /dev/null -w '%{http_code}' "$url")" == "200" ]]; then
        echo "MisteR Dashboard ($profile) lancé : $url"
        echo "Journal : $log_file — arrêt : $script_dir/stop.sh $profile"
        exit 0
    fi
    sleep 0.5
done

echo "Le serveur ne répond pas en 200 sur $url après 10 s. Journal :" >&2
tail -n 20 "$log_file" >&2
exit 1
