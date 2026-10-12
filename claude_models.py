"""Modèles proposés pour une session Claude Code lancée dans Orca, et niveaux d'effort de chacun.

Claude Code garde en cache la liste des modèles du compte connecté, avec les niveaux d'effort que chacun
accepte, et la retélécharge lui-même quand elle a plus d'une heure : la relire à chaque demande suffit
pour que le dialogue suive les sorties de modèles, sans code ni configuration à changer. Ce cache n'est
pas documenté : absent, illisible ou d'un autre format, la liste se réduit aux alias, avec tous les
niveaux.
"""
import json
import os
import re
from pathlib import Path

# Alias de `claude --model`, qui désignent toujours la dernière version de chaque modèle.
ALIASES = ("fable", "opus", "sonnet", "haiku")
# Niveaux de `claude --effort`, du plus économe au plus poussé.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Seuls noms admis, alias compris : la commande lancée dans Orca passe par un shell.
SAFE_ID = re.compile(r"^claude-[a-z0-9-]+$")
FAMILY = re.compile(r"^claude-([a-z]+)-")
RECOMMENDED_BADGE = "Recommended"


def cache_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "cache" / "model-catalog"


def choices(directory=None):
    """[{"id", "label", "alias", "version", "efforts", "recommended"}] : les alias d'abord, puis les
    versions, principales d'abord. version : celle que désigne un alias, si le cache la donne. efforts
    vide : le modèle n'en accepte aucun."""
    versions = _versions(directory or cache_dir())
    latest = {}
    for version in versions:
        latest.setdefault(version["family"], version)
    aliases = []
    for alias in ALIASES:
        version = latest.get(alias)
        # Une famille absente du cache n'est pas proposée au compte.
        if versions and version is None:
            continue
        aliases.append({
            "id": alias,
            "label": alias.capitalize(),
            "alias": True,
            "version": version["label"] if version else None,
            "efforts": version["efforts"] if version else list(EFFORTS),
            "recommended": version["recommended"] if version else None,
        })
    return aliases + [
        {key: value for key, value in version.items() if key not in ("family", "main")}
        for version in versions
    ]


def find(model_id):
    """Le modèle proposé de ce nom, ou None."""
    return next((choice for choice in choices() if choice["id"] == model_id), None)


def _versions(directory):
    try:
        files = sorted(directory.glob("*-cc.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not files:
            return []
        models = json.loads(files[0].read_text(encoding="utf-8"))["catalog"]["config"]["models"]
        versions = [_version(model) for model in models]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    # Tri stable : l'ordre du cache, les modèles principaux avant les plus anciens.
    return sorted([version for version in versions if version], key=lambda version: not version["main"])


def _version(model):
    model_id = model.get("id")
    family = FAMILY.match(model_id) if isinstance(model_id, str) and SAFE_ID.match(model_id) else None
    if not family:
        return None
    options = (model.get("thinking") or {}).get("effort_options") or []
    efforts = [option["id"] for option in options if option.get("id") in EFFORTS]
    recommended = next(
        (option["id"] for option in options
         if option.get("id") in EFFORTS and (option.get("badge") or {}).get("message") == RECOMMENDED_BADGE),
        None
    )
    return {
        "id": model_id,
        "label": model.get("name") or model_id,
        "alias": False,
        "version": None,
        "efforts": efforts,
        "recommended": recommended,
        "family": family.group(1),
        "main": model.get("section") == "main",
    }
