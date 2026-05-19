import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_SCHOOL_NAME = "筑波大学附属中学校"
DEFAULT_SCHOOL_TYPE = "junior_high"
SCHOOL_TYPE_LABELS = {
    "junior_high": "中学",
    "high": "高校",
}
BOT_SETTINGS_FILE = Path("bot_settings.json")


def load_bot_settings() -> dict[str, dict[str, Any]]:
    if not BOT_SETTINGS_FILE.exists():
        return {}

    with BOT_SETTINGS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return {}
    return data


def save_bot_settings(settings: dict[str, dict[str, Any]]) -> None:
    BOT_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{BOT_SETTINGS_FILE.name}.",
        suffix=".tmp",
        dir=str(BOT_SETTINGS_FILE.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
            f.write("\n")
        os.replace(tmp_path, BOT_SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def get_guild_settings(guild_id: int | str) -> dict[str, Any]:
    settings = load_bot_settings()
    guild_key = str(guild_id)
    guild_settings = settings.get(guild_key)
    if isinstance(guild_settings, dict):
        return guild_settings
    return {}


def get_school_name_for_guild(guild_id: int | str | None) -> str:
    if guild_id is None:
        return DEFAULT_SCHOOL_NAME

    school_name = get_guild_settings(guild_id).get("school_name")
    if isinstance(school_name, str) and school_name.strip():
        return school_name.strip()
    return DEFAULT_SCHOOL_NAME


def normalize_school_type(school_type: str | None) -> str:
    if school_type in {"high", "高校", "高等学校"}:
        return "high"
    return DEFAULT_SCHOOL_TYPE


def get_school_type_for_guild(guild_id: int | str | None) -> str:
    if guild_id is None:
        return DEFAULT_SCHOOL_TYPE

    school_type = get_guild_settings(guild_id).get("school_type")
    if isinstance(school_type, str):
        return normalize_school_type(school_type)
    return DEFAULT_SCHOOL_TYPE


def set_school_name_for_guild(guild_id: int | str, school_name: str) -> None:
    settings = load_bot_settings()
    guild_key = str(guild_id)
    settings.setdefault(guild_key, {})
    settings[guild_key]["school_name"] = school_name.strip()
    save_bot_settings(settings)


def set_school_for_guild(
    guild_id: int | str,
    school_name: str,
    school_type: str,
) -> None:
    settings = load_bot_settings()
    guild_key = str(guild_id)
    settings.setdefault(guild_key, {})
    settings[guild_key]["school_name"] = school_name.strip()
    settings[guild_key]["school_type"] = normalize_school_type(school_type)
    save_bot_settings(settings)


def unset_school_name_for_guild(guild_id: int | str) -> None:
    settings = load_bot_settings()
    guild_key = str(guild_id)
    if guild_key not in settings:
        return

    settings[guild_key].pop("school_name", None)
    settings[guild_key].pop("school_type", None)
    if not settings[guild_key]:
        del settings[guild_key]
    save_bot_settings(settings)


def get_channel_id_for_guild(
    guild_id: int | str,
    key: str,
    legacy_key: str | None = None,
) -> str | None:
    guild_settings = get_guild_settings(guild_id)
    channel_id = guild_settings.get(key)
    if channel_id is None and legacy_key is not None:
        channel_id = guild_settings.get(legacy_key)
    if channel_id is None:
        return None
    return str(channel_id)


def set_channel_id_for_guild(guild_id: int | str, key: str, channel_id: int | str) -> None:
    settings = load_bot_settings()
    guild_key = str(guild_id)
    settings.setdefault(guild_key, {})
    settings[guild_key][key] = str(channel_id)
    save_bot_settings(settings)


def unset_channel_id_for_guild(
    guild_id: int | str,
    key: str,
    legacy_key: str | None = None,
) -> bool:
    settings = load_bot_settings()
    guild_key = str(guild_id)
    if guild_key not in settings:
        return False

    removed = settings[guild_key].pop(key, None) is not None
    if legacy_key is not None:
        removed = settings[guild_key].pop(legacy_key, None) is not None or removed

    if not settings[guild_key]:
        del settings[guild_key]
    save_bot_settings(settings)
    return removed


def iter_guild_settings() -> list[tuple[str, dict[str, Any]]]:
    return [
        (str(guild_id), guild_settings)
        for guild_id, guild_settings in load_bot_settings().items()
        if isinstance(guild_settings, dict)
    ]
