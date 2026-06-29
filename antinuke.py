"""
antinuke.py — Core detection engine.

Architecture:
  - Per-guild action counters stored in memory (defaultdict of deques)
  - Each event handler fires, increments the counter, checks threshold
  - If threshold exceeded → immediate punishment (asyncio.create_task for speed)
  - Whitelist checked FIRST before any action
  - Audit log executor fetched with up to 3 retries (0.5s apart) to handle Discord's delay
  - Ban tracker records every ban with timestamp for post-nuke auto-unban
  - On nuke detection: restore_guild() runs concurrently alongside punishment
  - Config cached in memory to avoid JSON reads on every event
"""

import discord
from discord.ext import commands
import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
import logging
from config import db
from logger import send_log

log = logging.getLogger("antinuke.engine")


# ── In-memory rate-limit buckets ──────────────────────────────────────────────
# counters[guild_id][user_id][action] = deque of timestamps
counters: dict[int, dict[int, dict[str, deque]]] = defaultdict(
    lambda: defaultdict(lambda: defaultdict(deque))
)

# Track users already being punished to avoid double-punishment
punishing: set[tuple[int, int]] = set()  # (guild_id, user_id)

# Ban tracker: guild_id → list of (user_id, timestamp) recorded by on_member_ban
# Used by auto-unban to know who was banned during a nuke window
_ban_log: dict[int, list[tuple[int, datetime]]] = defaultdict(list)

# Config cache: guild_id → (config_dict, cached_at)
# Invalidated every 60s so changes made via ,antinuke commands propagate quickly
_config_cache: dict[int, tuple[dict, datetime]] = {}
_CONFIG_TTL = 60  # seconds

# Executor cache: (guild_id, action) → (member, cached_at)
# Si el mismo action vuelve a ocurrir en 5s, skip audit log fetch
_executor_cache: dict = {}
_EXECUTOR_TTL = 5  # seconds


# ── Config cache ──────────────────────────────────────────────────────────────

def _get_config(guild_id: int) -> dict:
    """Return guild config from cache, refreshing if stale."""
    now = datetime.now(timezone.utc)
    entry = _config_cache.get(guild_id)
    if entry:
        config, cached_at = entry
        if (now - cached_at).total_seconds() < _CONFIG_TTL:
            return config
    config = db.get_guild(guild_id)
    _config_cache[guild_id] = (config, now)
    return config


def invalidate_config_cache(guild_id: int):
    """Call this after any ,antinuke / ,settings command that changes config."""
    _config_cache.pop(guild_id, None)


# ── Whitelist / rate-limit helpers ────────────────────────────────────────────

def _is_whitelisted(guild_id: int, user_id: int, bot_owner_ids: set) -> bool:
    if user_id in bot_owner_ids:
        return True
    config = _get_config(guild_id)
    return user_id in config.get("whitelist", [])


def _check_rate(guild_id: int, user_id: int, action: str, threshold: int, window: float) -> bool:
    """
    Push a new timestamp and return True if the user has hit the threshold
    within the rolling time window.
    """
    now = datetime.now(timezone.utc)
    bucket = counters[guild_id][user_id][action]
    bucket.append(now)
    cutoff = now - timedelta(seconds=window)
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return len(bucket) >= threshold


# ── Audit log executor fetch with retry ───────────────────────────────────────

async def _get_executor_with_retry(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    *,
    retries: int = 3,
) -> discord.Member | None:
    """
    Fetch the executor for `action`.
    - Si hay un ejecutor cacheado para este action en los últimos 5s, lo retorna inmediato.
    - Si no, intenta 3 veces con delays 0s, 0.3s, 0.5s (más agresivo que antes).
    - Guarda el resultado en caché para el siguiente evento.
    """
    cache_key = (guild.id, str(action))
    now = datetime.now(timezone.utc)

    # Hit de caché: mismo ejecutor, mismo action, hace menos de 5s
    cached = _executor_cache.get(cache_key)
    if cached:
        member, cached_at = cached
        if (now - cached_at).total_seconds() < _EXECUTOR_TTL:
            # Verificar que el miembro sigue en el servidor
            if guild.get_member(member.id):
                return member

    delays = [0, 0.3, 0.5]
    for attempt in range(retries):
        if delays[attempt] > 0:
            await asyncio.sleep(delays[attempt])
        try:
            async for entry in guild.audit_logs(limit=1, action=action):
                age = (now - entry.created_at).total_seconds()
                if age > 10:
                    break
                executor = guild.get_member(entry.user_id)
                if executor:
                    _executor_cache[cache_key] = (executor, now)
                    return executor
        except (discord.Forbidden, discord.HTTPException):
            return None

    return None


# ── Punishment ────────────────────────────────────────────────────────────────

async def _punish(guild: discord.Guild, member: discord.Member, punishment: str):
    """Execute the configured punishment. Called via create_task."""
    key = (guild.id, member.id)
    if key in punishing:
        return
    punishing.add(key)
    try:
        if not guild.me.guild_permissions.administrator:
            return

        if punishment == "ban":
            await guild.ban(member, reason="AntiNuke: automatic protection", delete_message_days=0)
        elif punishment == "kick":
            await guild.kick(member, reason="AntiNuke: automatic protection")
        elif punishment == "strip":
            roles_to_remove = [
                r for r in member.roles
                if r != guild.default_role and r.is_assignable()
            ]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="AntiNuke: roles stripped")
        elif punishment == "mute":
            until = discord.utils.utcnow() + timedelta(days=28)
            await member.timeout(until, reason="AntiNuke: automatic mute")
    except discord.Forbidden:
        log.warning(f"Missing permissions to punish {member} in {guild.name}")
    except Exception as e:
        log.error(f"Punishment error for {member} in {guild.name}: {e}")
    finally:
        await asyncio.sleep(30)
        punishing.discard(key)


# ── Auto-unban ────────────────────────────────────────────────────────────────

async def _auto_unban(guild: discord.Guild, nuke_detected_at: datetime, window: float = 30.0):
    """
    Unban all users that were banned within `window` seconds before nuke detection.
    Uses the in-memory ban log recorded by on_member_ban.
    """
    cutoff = nuke_detected_at - timedelta(seconds=window)
    victims = [
        uid for uid, ts in _ban_log.get(guild.id, [])
        if ts >= cutoff
    ]
    if not victims:
        return

    log.info(f"[{guild.name}] Auto-unban: {len(victims)} user(s) to unban.")

    async def _unban_one(uid: int):
        try:
            user = await guild.fetch_ban(discord.Object(id=uid))
            await guild.unban(user.user, reason="AntiNuke: reversing nuke ban")
        except discord.NotFound:
            pass
        except Exception as e:
            log.error(f"[{guild.name}] Failed to unban {uid}: {e}")

    # Run all unbans in parallel
    await asyncio.gather(*[_unban_one(uid) for uid in victims], return_exceptions=True)
    log.info(f"[{guild.name}] Auto-unban complete.")


# ── Central event handler ─────────────────────────────────────────────────────

async def _handle_event(
    guild: discord.Guild,
    executor: discord.Member | None,
    bot: commands.Bot,
    module_key: str,
    action_key: str,
    threshold_key: str,
    window_key: str,
    module_label: str,
    reason: str,
    extra_fields: list | None = None,
):
    """Central handler called by every event."""
    if executor is None:
        return
    if executor.id == bot.user.id:
        return
    if _is_whitelisted(guild.id, executor.id, bot.owner_ids):
        return
    if executor.top_role >= guild.me.top_role:
        return

    config = _get_config(guild.id)
    an = config.get("antinuke", {})

    if not an.get("enabled", False):
        return
    if not an.get(module_key, True):
        return

    threshold = an.get(threshold_key, 3)
    window = an.get(window_key, 10)

    hit = _check_rate(guild.id, executor.id, action_key, threshold, window)
    if not hit:
        return

    punishment = an.get("punishment", "ban")
    nuke_detected_at = datetime.now(timezone.utc)

    # Import here to avoid circular import (backup imports nothing from antinuke)
    try:
        from backup import restore_guild, get_snapshot
        has_backup = get_snapshot(guild.id) is not None
    except ImportError:
        has_backup = False
        restore_guild = None

    # Run punishment, log, auto-unban, and backup restore concurrently
    tasks = [
        asyncio.create_task(_punish(guild, executor, punishment)),
        asyncio.create_task(send_log(
            guild,
            action=punishment,
            target=executor,
            moderator=guild.me,
            reason=reason,
            module=module_label,
            extra_fields=extra_fields,
        )),
        asyncio.create_task(_auto_unban(guild, nuke_detected_at)),
    ]

    if has_backup and restore_guild:
        tasks.append(asyncio.create_task(restore_guild(guild, bot)))

    # Tasks are fire-and-forget; errors are caught inside each coroutine
    log.warning(
        f"[{guild.name}] AntiNuke triggered: {module_label} by {executor} "
        f"(threshold={threshold}/{window}s) → {punishment}"
        + (" + restore" if has_backup else "")
    )


# ── Cog ──────────────────────────────────────────────────────────────────────

class AntiNuke(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── helpers ───────────────────────────────────────────────────────────────

    def _check_account_age(self, guild_id: int, user: discord.Member | discord.User) -> bool:
        config = _get_config(guild_id)
        min_days = config["antinuke"].get("min_account_age_days", 0)
        if not min_days:
            return True
        age = (datetime.now(timezone.utc) - user.created_at).days
        return age >= min_days

    def _check_guild_age(self, guild_id: int, member: discord.Member) -> bool:
        config = _get_config(guild_id)
        min_days = config["antinuke"].get("min_guild_age_days", 0)
        if not min_days or not member.joined_at:
            return True
        age = (datetime.now(timezone.utc) - member.joined_at).days
        return age >= min_days

    # ── ANTI-BAN ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        # Track every ban for auto-unban (regardless of who did it)
        _ban_log[guild.id].append((user.id, datetime.now(timezone.utc)))
        # Prune entries older than 5 minutes to keep memory clean
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        _ban_log[guild.id] = [(uid, ts) for uid, ts in _ban_log[guild.id] if ts >= cutoff]

        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.ban)
        await _handle_event(
            guild, executor, self.bot,
            "anti_ban", "ban", "ban_threshold", "ban_window",
            "Anti-Ban",
            "Exceeded ban threshold",
            extra_fields=[("Banned User", f"`{user}` (`{user.id}`)", False)],
        )

    # ── ANTI-KICK ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.kick)
        if executor is None:
            return
        await _handle_event(
            guild, executor, self.bot,
            "anti_kick", "kick", "kick_threshold", "kick_window",
            "Anti-Kick",
            "Exceeded kick threshold",
            extra_fields=[("Kicked User", f"`{member}` (`{member.id}`)", False)],
        )

    # ── ANTI-CHANNEL DELETE ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.channel_delete)
        await _handle_event(
            guild, executor, self.bot,
            "anti_channel_delete", "channel_delete",
            "channel_delete_threshold", "channel_delete_window",
            "Anti-Channel Delete",
            "Exceeded channel deletion threshold",
            extra_fields=[("Deleted Channel", f"`#{channel.name}`", False)],
        )

    # ── ANTI-CHANNEL CREATE ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.channel_create)
        await _handle_event(
            guild, executor, self.bot,
            "anti_channel_create", "channel_create",
            "channel_create_threshold", "channel_create_window",
            "Anti-Channel Create",
            "Exceeded channel creation threshold",
            extra_fields=[("Created Channel", f"`#{channel.name}`", False)],
        )

    # ── ANTI-ROLE DELETE ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild = role.guild
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.role_delete)
        await _handle_event(
            guild, executor, self.bot,
            "anti_role_delete", "role_delete",
            "role_delete_threshold", "role_delete_window",
            "Anti-Role Delete",
            "Exceeded role deletion threshold",
            extra_fields=[("Deleted Role", f"`{role.name}`", False)],
        )

    # ── ANTI-ROLE CREATE ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        guild = role.guild
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.role_create)
        await _handle_event(
            guild, executor, self.bot,
            "anti_role_create", "role_create",
            "role_create_threshold", "role_create_window",
            "Anti-Role Create",
            "Exceeded role creation threshold",
            extra_fields=[("Created Role", f"`{role.name}`", False)],
        )

    # ── ANTI-WEBHOOK ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel):
        guild = channel.guild
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.webhook_create)
        await _handle_event(
            guild, executor, self.bot,
            "anti_webhook", "webhook_create",
            "webhook_create_threshold", "webhook_create_window",
            "Anti-Webhook",
            "Exceeded webhook creation threshold",
            extra_fields=[("Channel", f"`#{channel.name}`", False)],
        )

    # ── ANTI-MENTION SPAM ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not message.author:
            return
        if message.author.bot:
            return

        guild = message.guild
        config = _get_config(guild.id)
        an = config.get("antinuke", {})

        if not an.get("enabled", False):
            return

        # Anti-everyone mention
        if an.get("anti_everyone_mention", True):
            if message.mention_everyone:
                if not _is_whitelisted(guild.id, message.author.id, self.bot.owner_ids):
                    executor = guild.get_member(message.author.id)
                    if executor:
                        asyncio.create_task(_punish(guild, executor, an.get("punishment", "ban")))
                        asyncio.create_task(send_log(
                            guild,
                            action=an.get("punishment", "ban"),
                            target=executor,
                            moderator=guild.me,
                            reason="Used @everyone / @here mention",
                            module="Anti-Everyone Mention",
                        ))
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        return

        # Mass mention threshold
        if an.get("anti_mention", True):
            threshold = an.get("mention_threshold", 10)
            window = an.get("mention_window", 8)
            mentions = len(set(message.mentions))
            if mentions == 0:
                return
            for _ in range(mentions):
                _check_rate(guild.id, message.author.id, "mention", 1, window)

            hit = _check_rate(guild.id, message.author.id, "mention_check", threshold, window)
            if hit and not _is_whitelisted(guild.id, message.author.id, self.bot.owner_ids):
                executor = guild.get_member(message.author.id)
                if executor and executor.top_role < guild.me.top_role:
                    asyncio.create_task(_punish(guild, executor, an.get("punishment", "ban")))
                    asyncio.create_task(send_log(
                        guild,
                        action=an.get("punishment", "ban"),
                        target=executor,
                        moderator=guild.me,
                        reason=f"Mass mention spam ({mentions} mentions)",
                        module="Anti-Mention Spam",
                        extra_fields=[("Mentions", str(mentions), True)],
                    ))
                    try:
                        await message.delete()
                    except Exception:
                        pass

    # ── ANTI-BOT ADD ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        config = _get_config(guild.id)
        an = config.get("antinuke", {})

        if not an.get("enabled", False):
            return

        if member.bot and an.get("anti_bot_add", True):
            executor = await _get_executor_with_retry(guild, discord.AuditLogAction.bot_add)
            if executor and not _is_whitelisted(guild.id, executor.id, self.bot.owner_ids):
                asyncio.create_task(guild.kick(member, reason="AntiNuke: unauthorized bot add"))
                asyncio.create_task(_punish(guild, executor, an.get("punishment", "ban")))
                asyncio.create_task(send_log(
                    guild,
                    action=an.get("punishment", "ban"),
                    target=executor,
                    moderator=guild.me,
                    reason="Unauthorized bot added to server",
                    module="Anti-Bot Add",
                    extra_fields=[("Bot Added", f"`{member}` (`{member.id}`)", False)],
                ))

        # Account age check
        min_age = an.get("min_account_age_days", 0)
        if min_age and not member.bot:
            age = (datetime.now(timezone.utc) - member.created_at).days
            if age < min_age:
                try:
                    await member.kick(reason=f"AntiNuke: account too new ({age}d, min {min_age}d)")
                    asyncio.create_task(send_log(
                        guild,
                        action="kick",
                        target=member,
                        moderator=guild.me,
                        reason=f"Account age below minimum ({age}/{min_age} days)",
                        module="Anti-New Account",
                        extra_fields=[
                            ("Account Age", f"`{age} days`", True),
                            ("Minimum Required", f"`{min_age} days`", True),
                        ],
                    ))
                except Exception:
                    pass

    # ── ANTI-GUILD UPDATE ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        guild = after
        config = _get_config(guild.id)
        an = config.get("antinuke", {})
        if not an.get("enabled", False) or not an.get("anti_server_update", True):
            return
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.guild_update)
        if executor is None or _is_whitelisted(guild.id, executor.id, self.bot.owner_ids):
            return
        if executor.id == self.bot.user.id:
            return
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("Icon changed")
        if before.vanity_url_code != after.vanity_url_code:
            changes.append(f"Vanity: `{before.vanity_url_code}` → `{after.vanity_url_code}`")
        if not changes:
            return
        asyncio.create_task(_punish(guild, executor, an.get("punishment", "ban")))
        asyncio.create_task(send_log(
            guild,
            action=an.get("punishment", "ban"),
            target=executor,
            moderator=guild.me,
            reason="Unauthorized server update",
            module="Anti-Server Update",
            extra_fields=[("Changes", "\n".join(changes), False)],
        ))

    # ── ANTI-PRUNE ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        pass  # placeholder for future integration events

    @commands.Cog.listener()
    async def on_raw_member_remove(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        config = _get_config(guild.id)
        an = config.get("antinuke", {})
        if not an.get("enabled", False) or not an.get("anti_prune", True):
            return
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.member_prune)
        if executor and not _is_whitelisted(guild.id, executor.id, self.bot.owner_ids):
            asyncio.create_task(_punish(guild, executor, an.get("punishment", "ban")))
            asyncio.create_task(send_log(
                guild,
                action=an.get("punishment", "ban"),
                target=executor,
                moderator=guild.me,
                reason="Unauthorized member prune",
                module="Anti-Prune",
            ))

    # ── ANTI-EMOJI DELETE ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        if len(before) <= len(after):
            return
        config = _get_config(guild.id)
        an = config.get("antinuke", {})
        if not an.get("enabled", False) or not an.get("anti_emoji_delete", True):
            return
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.emoji_delete)
        deleted = len(before) - len(after)
        await _handle_event(
            guild, executor, self.bot,
            "anti_emoji_delete", "emoji_delete",
            "emoji_delete_threshold", "emoji_delete_window",
            "Anti-Emoji Delete",
            f"Bulk emoji deletion ({deleted} emojis)",
            extra_fields=[("Deleted", f"`{deleted} emojis`", True)],
        )

    # ── ANTI-ROLE PERMISSIONS UPDATE ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        guild = after.guild
        config = _get_config(guild.id)
        an = config.get("antinuke", {})
        if not an.get("enabled", False):
            return
        gained = []
        for perm_flag in ["administrator", "ban_members", "manage_guild", "manage_roles", "manage_channels", "kick_members"]:
            if not getattr(before.permissions, perm_flag) and getattr(after.permissions, perm_flag):
                gained.append(perm_flag.replace("_", " ").title())
        if not gained:
            return
        executor = await _get_executor_with_retry(guild, discord.AuditLogAction.role_update)
        if executor is None or _is_whitelisted(guild.id, executor.id, self.bot.owner_ids):
            return
        asyncio.create_task(_punish(guild, executor, an.get("punishment", "ban")))
        asyncio.create_task(send_log(
            guild,
            action=an.get("punishment", "ban"),
            target=executor,
            moderator=guild.me,
            reason="Dangerous permissions granted to role",
            module="Anti-Role Permissions",
            extra_fields=[
                ("Role", f"`{after.name}`", True),
                ("Permissions Granted", ", ".join(f"`{p}`" for p in gained), False),
            ],
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiNuke(bot))
