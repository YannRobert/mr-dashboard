"""Modèles proposés pour une session Claude Code lancée dans Orca, et niveaux d'effort de chacun.

Claude Code garde en cache la liste des modèles du compte connecté, avec les niveaux d'effort que chacun
accepte, et la retélécharge lui-même quand elle a plus d'une heure : la relire à chaque demande suffit
pour que le dialogue suive les sorties de modèles, sans code ni configuration à changer. La liste la
plus récente dit ce que désigne chaque alias ; les versions précises s'y ajoutent de toutes les listes
du cache, une liste récente se réduisant parfois aux dernières versions, quand les plus anciennes
restent très utilisées. Ce cache n'est pas documenté : absent, illisible ou d'un autre format, la liste
se réduit aux alias, avec tous les niveaux.
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
# Suffixe de date d'un nom de version (claude-haiku-4-5-20251001), qui ne la distingue pas d'une autre.
DATE_SUFFIX = re.compile(r"-\d{8}$")
RECOMMENDED_BADGE = "Recommended"


def cache_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "cache" / "model-catalog"


def choices(directory=None):
    """[{"id", "label", "alias", "version", "efforts", "recommended"}] : les alias d'abord, puis les
    versions précises qu'aucun alias ne désigne, par famille et de la plus récente à la plus ancienne.
    version : celle que désigne un alias, si le cache la donne. efforts vide : le modèle n'en accepte
    aucun."""
    lists = _lists(directory or cache_dir())
    current = lists[0] if lists else []
    latest = {}
    for version in sorted(current, key=lambda version: not version["main"]):
        latest.setdefault(version["family"], version)
    aliases = []
    for alias in ALIASES:
        version = latest.get(alias)
        # Une famille absente de la liste la plus récente n'est plus proposée au compte.
        if current and version is None:
            continue
        aliases.append({
            "id": alias,
            "label": alias.capitalize(),
            "alias": True,
            "version": version["label"] if version else None,
            "efforts": version["efforts"] if version else list(EFFORTS),
            "recommended": version["recommended"] if version else None,
        })
    designated = {version["id"] for version in latest.values()}
    versions = {}
    for version in (version for versions_list in lists for version in versions_list):
        if version["id"] not in designated and version["family"] in ALIASES:
            versions.setdefault(version["id"], version)
    ordered = sorted(versions.values(), key=lambda version: (ALIASES.index(version["family"]), _number(version)))
    return aliases + [{key: value for key, value in version.items() if key not in ("family", "main")} for version in ordered]


def find(model_id):
    """Le modèle proposé de ce nom, ou None."""
    return next((choice for choice in choices() if choice["id"] == model_id), None)


# Clé de tri d'une version, la plus récente d'abord : claude-opus-4-8 avant claude-opus-4-6, et
# claude-fable-5-1 avant claude-fable-5, lu 5.0.
def _number(version):
    digits = [-int(digit) for digit in DATE_SUFFIX.sub("", version["id"]).split("-")[2:] if digit.isdigit()]
    return digits + [0] * (2 - len(digits))


def _lists(directory):
    """Les versions de chaque liste du cache, la plus récente d'abord ; une liste illisible est ignorée."""
    try:
        files = sorted(directory.glob("*-cc.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    lists = []
    for path in files:
        try:
            models = json.loads(path.read_text(encoding="utf-8"))["catalog"]["config"]["models"]
            versions = [version for version in (_version(model) for model in models) if version]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if versions:
            lists.append(versions)
    return lists


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
