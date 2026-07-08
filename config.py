import json
from pathlib import Path

DEFAULT_PREFIX = ","

DATA_DIR = Path("data")
DB_FILE = DATA_DIR / "db.json"


def default_guild_config() -> dict:
    return {
        "prefix": DEFAULT_PREFIX,
        "log_channel": None,
        "whitelist": [],
        "antinuke": {
            "enabled": False,
            "punishment": "ban",
            "ban_threshold": 3,
            "kick_threshold": 3,
            "channel_delete_threshold": 3,
            "channel_create_threshold": 3,
            "role_delete_threshold": 3,
            "role_create_threshold": 3,
            "webhook_create_threshold": 3,
            "mention_threshold": 10,
            "emoji_delete_threshold": 5,
            "ban_window": 10,
            "kick_window": 10,
            "channel_delete_window": 10,
            "channel_create_window": 10,
            "role_delete_window": 10,
            "role_create_window": 10,
            "webhook_create_window": 10,
            "mention_window": 8,
            "emoji_delete_window": 10,
            "anti_ban": True,
            "anti_kick": True,
            "anti_channel_delete": True,
            "anti_channel_create": True,
            "anti_role_delete": True,
            "anti_role_create": True,
            "anti_webhook": True,
            "anti_mention": True,
            "anti_emoji_delete": True,
            "anti_bot_add": True,
            "anti_everyone_mention": True,
            "anti_server_update": True,
            "anti_prune": True,
            "min_account_age_days": 0,
            "min_guild_age_days": 0,
        },
        "log_embed": {
            "color": 0x2b2d31,
            "footer_text": "AntiNuke Protection",
            "thumbnail": True,
        }
    }


def _load() -> dict:
    if not DB_FILE.exists():
        return {"meta": {}, "guilds": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("meta", {})
    data.setdefault("guilds", {})
    return data


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Database:
    def get(self, key, default=None):
        return _load()["meta"].get(key, default)

    def set(self, key, value):
        data = _load()
        data["meta"][key] = value
        _save(data)

    def get_guild(self, guild_id: int) -> dict:
        data = _load()
        gid = str(guild_id)
        if gid in data["guilds"]:
            return data["guilds"][gid]
        config = default_guild_config()
        data["guilds"][gid] = config
        _save(data)
        return config

    def update_guild(self, guild_id: int, config: dict):
        config.pop("_id", None)
        data = _load()
        data["guilds"][str(guild_id)] = config
        _save(data)


db = Database()
