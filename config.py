import json
import os
import threading
from pathlib import Path

DEFAULT_PREFIX = ","
DATA_PATH = Path("data/db.json")


class Database:
    """Thread-safe JSON-backed database."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data = {}
        self._load()

    def _load(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            with open(self._path, "r") as f:
                self._data = json.load(f)
        else:
            self._data = {}
            self._save_unsafe()

    def _save_unsafe(self):
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def save(self):
        with self._lock:
            self._save_unsafe()

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._data[key] = value
            self._save_unsafe()

    def get_guild(self, guild_id: int) -> dict:
        gid = str(guild_id)
        with self._lock:
            if gid not in self._data.get("guilds", {}):
                if "guilds" not in self._data:
                    self._data["guilds"] = {}
                self._data["guilds"][gid] = default_guild_config()
                self._save_unsafe()
            return self._data["guilds"][gid]

    def update_guild(self, guild_id: int, config: dict):
        gid = str(guild_id)
        with self._lock:
            if "guilds" not in self._data:
                self._data["guilds"] = {}
            self._data["guilds"][gid] = config
            self._save_unsafe()


def default_guild_config() -> dict:
    return {
        "prefix": DEFAULT_PREFIX,
        "log_channel": None,
        "whitelist": [],          # list of user IDs (int)
        "antinuke": {
            "enabled": False,
            "punishment": "ban",  # ban | kick | strip | mute
            # ── thresholds ──────────────────────────────────────
            "ban_threshold": 3,
            "kick_threshold": 3,
            "channel_delete_threshold": 3,
            "channel_create_threshold": 3,
            "role_delete_threshold": 3,
            "role_create_threshold": 3,
            "webhook_create_threshold": 3,
            "mention_threshold": 10,
            "emoji_delete_threshold": 5,
            # ── time windows (seconds) ───────────────────────────
            "ban_window": 10,
            "kick_window": 10,
            "channel_delete_window": 10,
            "channel_create_window": 10,
            "role_delete_window": 10,
            "role_create_window": 10,
            "webhook_create_window": 10,
            "mention_window": 8,
            "emoji_delete_window": 10,
            # ── module toggles ───────────────────────────────────
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
            # ── extra filters ────────────────────────────────────
            "min_account_age_days": 0,    # 0 = disabled
            "min_guild_age_days": 0,      # 0 = disabled
        },
        "log_embed": {
            "color": 0x2b2d31,
            "footer_text": "AntiNuke Protection",
            "thumbnail": True,            # use server icon
        }
    }


db = Database(DATA_PATH)
