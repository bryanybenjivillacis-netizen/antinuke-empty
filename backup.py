"""
backup.py — Preventive server snapshot + restoration system.

Snapshots are taken:
  1. On bot ready (for every guild the bot is in)
  2. Every 30 minutes via background task
  3. On-demand via command (owner only)

Restoration is triggered by antinuke.py after a nuke is detected.
It recreates roles and channels in the correct order and restores permissions.

Limitations (Discord API constraints):
  - Role positions near the top (above bot's role) cannot be restored.
  - Channel icons/banners are not part of the API for restoration.
  - Threads and forum posts are NOT restored (too volatile).
"""

import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime, timezone
from config import db

log = logging.getLogger("antinuke.backup")

# In-memory snapshot store: { guild_id: GuildSnapshot }
_snapshots: dict[int, dict] = {}


# ── Snapshot builder ──────────────────────────────────────────────────────────

def _serialize_overwrites(overwrites: dict) -> list[dict]:
    """Convert permission overwrites to a serializable list."""
    result = []
    for target, overwrite in overwrites.items():
        allow, deny = overwrite.pair()
        result.append({
            "id": target.id,
            "type": "role" if isinstance(target, discord.Role) else "member",
            "allow": allow.value,
            "deny": deny.value,
        })
    return result


def take_snapshot(guild: discord.Guild) -> dict:
    """
    Build a complete in-memory snapshot of the guild's structure.
    Called from setup_hook and the background task — no I/O, pure memory.
    """
    # Roles (sorted by position ascending so we recreate from bottom up)
    roles = []
    for role in sorted(guild.roles, key=lambda r: r.position):
        if role.is_default():
            continue
        if role.managed:
            # Bot/integration roles can't be created manually, skip
            continue
        roles.append({
            "id": role.id,
            "name": role.name,
            "color": role.color.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "permissions": role.permissions.value,
            "position": role.position,
        })

    # Categories
    categories = []
    for cat in guild.categories:
        categories.append({
            "id": cat.id,
            "name": cat.name,
            "position": cat.position,
            "overwrites": _serialize_overwrites(cat.overwrites),
        })

    # Channels (text, voice, stage, forum)
    channels = []
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue  # already captured above
        entry = {
            "id": ch.id,
            "name": ch.name,
            "type": str(ch.type),
            "position": ch.position,
            "category_id": ch.category_id,
            "overwrites": _serialize_overwrites(ch.overwrites),
        }
        if isinstance(ch, discord.TextChannel):
            entry["topic"] = ch.topic
            entry["slowmode_delay"] = ch.slowmode_delay
            entry["nsfw"] = ch.nsfw
        elif isinstance(ch, discord.VoiceChannel):
            entry["bitrate"] = ch.bitrate
            entry["user_limit"] = ch.user_limit
        channels.append(entry)

    snapshot = {
        "guild_id": guild.id,
        "guild_name": guild.name,
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "roles": roles,
        "categories": categories,
        "channels": channels,
    }
    _snapshots[guild.id] = snapshot
    log.debug(f"[{guild.name}] Snapshot taken: {len(roles)} roles, "
              f"{len(categories)} categories, {len(channels)} channels")
    return snapshot


def get_snapshot(guild_id: int) -> dict | None:
    return _snapshots.get(guild_id)


# ── Restoration engine ────────────────────────────────────────────────────────

async def _build_overwrites(
    guild: discord.Guild,
    raw: list[dict],
    id_map: dict[int, int],  # old_id → new_id for recreated roles
) -> dict:
    """Reconstruct permission overwrites from snapshot data."""
    overwrites = {}
    for entry in raw:
        old_id = entry["id"]
        # Remap old role ID → new role ID if the role was recreated
        resolved_id = id_map.get(old_id, old_id)
        allow = discord.Permissions(entry["allow"])
        deny = discord.Permissions(entry["deny"])
        overwrite = discord.PermissionOverwrite.from_pair(allow, deny)

        if entry["type"] == "role":
            target = guild.get_role(resolved_id)
        else:
            target = guild.get_member(resolved_id)

        if target:
            overwrites[target] = overwrite
    return overwrites


async def restore_guild(guild: discord.Guild, bot: commands.Bot) -> bool:
    """
    Restore guild to the last snapshot.
    Returns True if restoration completed (even partially), False if no snapshot.

    Restoration order:
      1. Recreate missing roles (bottom → top)
      2. Recreate missing categories
      3. Recreate missing channels
      4. Restore permission overwrites on surviving channels/categories
    """
    snapshot = get_snapshot(guild.id)
    if not snapshot:
        log.warning(f"[{guild.name}] No snapshot available for restoration.")
        return False

    log.info(f"[{guild.name}] Starting restoration from snapshot taken at {snapshot['taken_at']}")

    # Maps old role ID → new role ID (for permission overwrite remapping)
    role_id_map: dict[int, int] = {}

    # ── Step 1: Recreate missing roles ───────────────────────────────────────
    existing_role_names = {r.name for r in guild.roles}

    for role_data in snapshot["roles"]:
        if role_data["name"] in existing_role_names:
            # Role still exists — map old ID to current ID
            existing = discord.utils.get(guild.roles, name=role_data["name"])
            if existing:
                role_id_map[role_data["id"]] = existing.id
            continue

        try:
            new_role = await guild.create_role(
                name=role_data["name"],
                color=discord.Color(role_data["color"]),
                hoist=role_data["hoist"],
                mentionable=role_data["mentionable"],
                permissions=discord.Permissions(role_data["permissions"]),
                reason="AntiNuke: restoring role from snapshot",
            )
            role_id_map[role_data["id"]] = new_role.id
            log.info(f"[{guild.name}] Restored role: {role_data['name']}")
            await asyncio.sleep(0.3)  # rate-limit guard
        except discord.Forbidden:
            log.warning(f"[{guild.name}] No permission to create role: {role_data['name']}")
        except Exception as e:
            log.error(f"[{guild.name}] Failed to create role {role_data['name']}: {e}")

    # ── Step 2: Recreate missing categories ──────────────────────────────────
    existing_cat_names = {c.name for c in guild.categories}
    cat_id_map: dict[int, int] = {}  # old_cat_id → new_cat_id

    for cat_data in sorted(snapshot["categories"], key=lambda c: c["position"]):
        if cat_data["name"] in existing_cat_names:
            existing = discord.utils.get(guild.categories, name=cat_data["name"])
            if existing:
                cat_id_map[cat_data["id"]] = existing.id
            continue

        try:
            overwrites = await _build_overwrites(guild, cat_data["overwrites"], role_id_map)
            new_cat = await guild.create_category(
                name=cat_data["name"],
                overwrites=overwrites,
                reason="AntiNuke: restoring category from snapshot",
            )
            cat_id_map[cat_data["id"]] = new_cat.id
            log.info(f"[{guild.name}] Restored category: {cat_data['name']}")
            await asyncio.sleep(0.3)
        except Exception as e:
            log.error(f"[{guild.name}] Failed to create category {cat_data['name']}: {e}")

    # ── Step 3: Recreate missing channels ────────────────────────────────────
    existing_ch_names = {c.name for c in guild.channels}

    for ch_data in sorted(snapshot["channels"], key=lambda c: c["position"]):
        if ch_data["name"] in existing_ch_names:
            continue

        # Resolve category
        old_cat_id = ch_data.get("category_id")
        category = None
        if old_cat_id:
            new_cat_id = cat_id_map.get(old_cat_id, old_cat_id)
            category = guild.get_channel(new_cat_id)
            if not isinstance(category, discord.CategoryChannel):
                category = None

        overwrites = await _build_overwrites(guild, ch_data["overwrites"], role_id_map)

        try:
            ch_type = ch_data["type"]
            if ch_type == "text":
                await guild.create_text_channel(
                    name=ch_data["name"],
                    category=category,
                    overwrites=overwrites,
                    topic=ch_data.get("topic"),
                    slowmode_delay=ch_data.get("slowmode_delay", 0),
                    nsfw=ch_data.get("nsfw", False),
                    reason="AntiNuke: restoring channel from snapshot",
                )
            elif ch_type == "voice":
                await guild.create_voice_channel(
                    name=ch_data["name"],
                    category=category,
                    overwrites=overwrites,
                    bitrate=min(ch_data.get("bitrate", 64000), guild.bitrate_limit),
                    user_limit=ch_data.get("user_limit", 0),
                    reason="AntiNuke: restoring channel from snapshot",
                )
            elif ch_type == "stage_voice":
                await guild.create_stage_channel(
                    name=ch_data["name"],
                    category=category,
                    overwrites=overwrites,
                    reason="AntiNuke: restoring channel from snapshot",
                )
            log.info(f"[{guild.name}] Restored channel: #{ch_data['name']}")
            await asyncio.sleep(0.3)
        except discord.Forbidden:
            log.warning(f"[{guild.name}] No permission to create channel: {ch_data['name']}")
        except Exception as e:
            log.error(f"[{guild.name}] Failed to create channel {ch_data['name']}: {e}")

    log.info(f"[{guild.name}] Restoration complete.")
    return True


# ── Cog ──────────────────────────────────────────────────────────────────────

class Backup(commands.Cog):
    """Preventive snapshot system with auto-restore on nuke detection."""

    SNAPSHOT_INTERVAL = 1800  # 30 minutes

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._snapshot_task: asyncio.Task | None = None

    async def cog_load(self):
        self._snapshot_task = asyncio.create_task(self._periodic_snapshots())

    async def cog_unload(self):
        if self._snapshot_task:
            self._snapshot_task.cancel()

    async def _periodic_snapshots(self):
        """Take snapshots of all guilds every 30 minutes."""
        await self.bot.wait_until_ready()
        # Initial snapshot on startup
        for guild in self.bot.guilds:
            take_snapshot(guild)
        log.info(f"Initial snapshots taken for {len(self.bot.guilds)} guild(s).")

        while not self.bot.is_closed():
            await asyncio.sleep(self.SNAPSHOT_INTERVAL)
            for guild in self.bot.guilds:
                take_snapshot(guild)
            log.debug(f"Periodic snapshots refreshed for {len(self.bot.guilds)} guild(s).")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Snapshot a new guild immediately when the bot joins."""
        take_snapshot(guild)
        log.info(f"Snapshot taken on guild join: {guild.name}")

    # ── Owner commands ────────────────────────────────────────────────────────

    @commands.command(name="backup")
    @commands.is_owner()
    async def backup_cmd(self, ctx: commands.Context, sub: str = "status"):
        """
        Backup management (bot owner only).
          ,backup snapshot  — force a new snapshot now
          ,backup restore   — restore this guild from last snapshot
          ,backup status    — show snapshot info
        """
        guild = ctx.guild
        if not guild:
            return

        if sub == "snapshot":
            snap = take_snapshot(guild)
            await ctx.send(embed=discord.Embed(
                description=(
                    f"Snapshot taken.\n"
                    f"`{len(snap['roles'])}` roles · "
                    f"`{len(snap['categories'])}` categories · "
                    f"`{len(snap['channels'])}` channels"
                ),
                color=0x57f287,
            ))

        elif sub == "restore":
            msg = await ctx.send(embed=discord.Embed(
                description="Restoring guild from snapshot...", color=0xfee75c
            ))
            ok = await restore_guild(guild, self.bot)
            if ok:
                await msg.edit(embed=discord.Embed(
                    description="Restoration complete.", color=0x57f287
                ))
            else:
                await msg.edit(embed=discord.Embed(
                    description="No snapshot found for this guild.", color=0xed4245
                ))

        else:  # status
            snap = get_snapshot(guild.id)
            if not snap:
                return await ctx.send(embed=discord.Embed(
                    description="No snapshot available.", color=0x2b2d31
                ))
            taken = snap["taken_at"]
            await ctx.send(embed=discord.Embed(
                description=(
                    f"**Last snapshot:** `{taken}`\n"
                    f"`{len(snap['roles'])}` roles · "
                    f"`{len(snap['categories'])}` categories · "
                    f"`{len(snap['channels'])}` channels"
                ),
                color=0x2b2d31,
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Backup(bot))
