import os
from pymongo import MongoClient

DEFAULT_PREFIX = ","

_client = MongoClient(os.getenv("MONGO_URI"))
_db = _client["bot2"]
_guilds = _db["guilds"]


def default_guild_config() -> dict:
    return {
        "prefix": DEFAULT_PREFIX,
        "log_channel": None,
        "modlog_channel": None,
        "whitelist": [],
        "antinuke_admins": [],
        "panic_active": False,
        "panic_state": {},
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
            "anti_role_add": True,
            "min_account_age_days": 0,
            "min_guild_age_days": 0,
        },
        "log_embed": {
            "color": 0x2b2d31,
            "footer_text": "AntiNuke Protection",
            "thumbnail": True,
        }
    }


class Database:
    def get(self, key, default=None):
        doc = _db["meta"].find_one({"_id": key})
        return doc.get("value", default) if doc else default

    def set(self, key, value):
        _db["meta"].replace_one({"_id": key}, {"_id": key, "value": value}, upsert=True)

    def get_guild(self, guild_id: int) -> dict:
        doc = _guilds.find_one({"_id": str(guild_id)})
        if doc:
            doc.pop("_id", None)
            return doc

        config = default_guild_config()
        _guilds.insert_one({"_id": str(guild_id), **config})
        return config

    def update_guild(self, guild_id: int, config: dict):
        config.pop("_id", None)
        _guilds.replace_one(
            {"_id": str(guild_id)},
            {"_id": str(guild_id), **config},
            upsert=True,
        )


db = Database()
