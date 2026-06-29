"""
vc_tracker.py — Real-time voice channel population tracker.

Tracks the total number of users across all VCs in a guild.
When the total crosses a configurable threshold multiple, sends an embed
to a designated channel.

Commands:
  ,setvc channel #canal    — configura canal de notificaciones automáticas
  ,setvc threshold <n>     — cada cuántas personas notifica (default 5)
  ,vcstats                 — manda embed con total exacto en VC (solo admins)
"""

import discord
from discord.ext import commands
from config import db
import logging

log = logging.getLogger("antinuke.vc_tracker")

# In-memory: guild_id → last notified milestone
_last_milestone: dict[int, int] = {}


def _get_vc_total(guild: discord.Guild) -> int:
    """Count total non-bot users across all voice channels using voice_states."""
    return sum(
        1 for member_id, state in guild.voice_states.items()
        if state.channel is not None
        and (m := guild.get_member(member_id)) is not None
        and not m.bot
    )


def _get_vc_config(guild_id: int) -> dict:
    config = db.get_guild(guild_id)
    return config.get("vc_tracker", {
        "channel_id": None,
        "threshold": 5,
        "enabled": False,
    })


def _save_vc_config(guild_id: int, vc_cfg: dict):
    config = db.get_guild(guild_id)
    config["vc_tracker"] = vc_cfg
    db.update_guild(guild_id, config)


def _build_embed(total: int, guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        description=f"**+{total}** en VC",
        color=0x2b2d31,
    )
    embed.set_footer(text=guild.name)
    return embed


class VCTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Voice state update ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        guild = member.guild
        vc_cfg = _get_vc_config(guild.id)

        if not vc_cfg.get("enabled") or not vc_cfg.get("channel_id"):
            return

        # Solo nos importan entradas y salidas, no mute/deafen/moves internos
        joined = after.channel is not None and before.channel != after.channel
        left = after.channel is None and before.channel is not None

        if not joined and not left:
            return

        total = _get_vc_total(guild)
        threshold = vc_cfg.get("threshold", 5)
        last = _last_milestone.get(guild.id, 0)

        if joined:
            current_milestone = (total // threshold) * threshold
            if current_milestone > last and current_milestone > 0:
                _last_milestone[guild.id] = current_milestone
                channel = guild.get_channel(int(vc_cfg["channel_id"]))
                if channel:
                    try:
                        await channel.send(embed=_build_embed(total, guild))
                    except discord.Forbidden:
                        log.warning(f"[{guild.name}] No permission to send VC notification.")
                    except Exception as e:
                        log.error(f"[{guild.name}] VC notification error: {e}")
        else:
            current_milestone = (total // threshold) * threshold
            if current_milestone < last:
                _last_milestone[guild.id] = current_milestone

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.group(name="setvc", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def setvc(self, ctx: commands.Context):
        """VC tracker — usa: ,setvc channel #canal | ,setvc threshold <n>"""
        await ctx.send(embed=discord.Embed(
            description="Usa `,setvc channel #canal` o `,setvc threshold <número>`.",
            color=0x2b2d31,
        ))

    @setvc.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def setvc_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Configura canal de notificaciones automáticas. Ejemplo: ,setvc channel #canal"""
        vc_cfg = _get_vc_config(ctx.guild.id)
        vc_cfg["channel_id"] = channel.id
        vc_cfg["enabled"] = True
        _save_vc_config(ctx.guild.id, vc_cfg)

        await ctx.send(embed=discord.Embed(
            description=f"Canal configurado: {channel.mention}",
            color=0x57f287,
        ))

    @setvc.command(name="threshold")
    @commands.has_permissions(manage_guild=True)
    async def setvc_threshold(self, ctx: commands.Context, n: int):
        """Configura cada cuántas personas notifica. Ejemplo: ,setvc threshold 10"""
        if n < 1:
            return await ctx.send(embed=discord.Embed(
                description="El umbral debe ser al menos `1`.",
                color=0xed4245,
            ))

        vc_cfg = _get_vc_config(ctx.guild.id)
        vc_cfg["threshold"] = n
        _save_vc_config(ctx.guild.id, vc_cfg)
        _last_milestone.pop(ctx.guild.id, None)

        await ctx.send(embed=discord.Embed(
            description=f"Notificación automática cada `{n}` personas en VC.",
            color=0x57f287,
        ))

    # ── ,vcstats ──────────────────────────────────────────────────────────────

    @commands.command(name="vcstats")
    @commands.has_permissions(manage_guild=True)
    async def vcstats(self, ctx: commands.Context):
        """Manda embed con el total exacto de personas en VC ahora mismo."""
        total = _get_vc_total(ctx.guild)
        await ctx.send(embed=_build_embed(total, ctx.guild))


async def setup(bot: commands.Bot):
    await bot.add_cog(VCTracker(bot))
