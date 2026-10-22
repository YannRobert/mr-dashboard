"""Models offered for a Claude Code session launched in Orca, and the effort levels of each.

Claude Code caches the model list of the logged-in account, with the effort levels each accepts, and
downloads it again by itself once it is more than an hour old: rereading it on every request is enough
for the dialog to follow model releases, with no code or configuration to change. The most recent list
says what each alias points to; specific versions are added from every list in the cache, since a
recent list sometimes comes down to the latest versions while older ones remain widely used. This cache
is undocumented: if it is missing, unreadable or in another format, the list comes down to the aliases,
with all levels.
"""
import json
import os
import re
from pathlib import Path

# Aliases of `claude --model`, which always point to the latest version of each model.
ALIASES = ("fable", "opus", "sonnet", "haiku")
# Levels of `claude --effort`, from the most frugal to the most thorough.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Only allowed names, besides aliases: the command launched in Orca goes through a shell.
SAFE_ID = re.compile(r"^claude-[a-z0-9-]+$")
FAMILY = re.compile(r"^claude-([a-z]+)-")
# Date suffix of a version name (claude-haiku-4-5-20251001), which does not distinguish it from another.
DATE_SUFFIX = re.compile(r"-\d{8}$")
RECOMMENDED_BADGE = "Recommended"


def cache_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "cache" / "model-catalog"


def choices(directory=None):
    """[{"id", "label", "alias", "version", "efforts", "recommended"}]: aliases first, then the specific
    versions no alias points to, by family and from newest to oldest. version: the one an alias points
    to, if the cache gives it. Empty efforts: the model accepts none."""
    lists = _lists(directory or cache_dir())
    current = lists[0] if lists else []
    latest = {}
    for version in sorted(current, key=lambda version: not version["main"]):
        latest.setdefault(version["family"], version)
    aliases = []
    for alias in ALIASES:
        version = latest.get(alias)
        # A family missing from the most recent list is no longer offered to the account.
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
    """The offered model with this name, or None."""
    return next((choice for choice in choices() if choice["id"] == model_id), None)


# Sort key of a version, newest first: claude-opus-4-8 before claude-opus-4-6, and
# claude-fable-5-1 before claude-fable-5, read as 5.0.
def _number(version):
    digits = [-int(digit) for digit in DATE_SUFFIX.sub("", version["id"]).split("-")[2:] if digit.isdigit()]
    return digits + [0] * (2 - len(digits))


def _lists(directory):
    """The versions of each list in the cache, most recent list first; an unreadable list is skipped."""
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
