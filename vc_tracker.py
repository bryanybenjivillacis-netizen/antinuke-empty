"""
vc_tracker.py — Real-time voice channel population tracker.

Tracks the total number of users across all VCs in a guild.
When the total crosses a configurable threshold multiple (default: 5),
sends an embed to a designated channel.

Commands:
  ,setvc #channel          — set the notification channel
  ,setvc threshold <n>     — set how many people trigger a notification
  ,setvc mention <on|off>  — toggle @everyone mention with notifications
  ,setvc off               — disable notifications
  ,setvc status            — show current config
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
        1 for member, state in guild.voice_states.items()
        if state.channel is not None
        and not guild.get_member(member).bot
        if guild.get_member(member)
    )


def _get_vc_config(guild_id: int) -> dict:
    config = db.get_guild(guild_id)
    return config.get("vc_tracker", {
        "channel_id": None,
        "threshold": 5,
        "enabled": False,
        "mention_everyone": False,
    })


def _save_vc_config(guild_id: int, vc_cfg: dict):
    config = db.get_guild(guild_id)
    config["vc_tracker"] = vc_cfg
    db.update_guild(guild_id, config)


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

        # Only care about joins (not moves between VCs or mute/deafen changes)
        joined = after.channel is not None and before.channel != after.channel
        left = after.channel is None and before.channel is not None

        if not joined and not left:
            return

        total = _get_vc_total(guild)
        threshold = vc_cfg.get("threshold", 5)
        last = _last_milestone.get(guild.id, 0)

        if joined:
            # Fire when we've accumulated `threshold` new joins since last notification
            current_milestone = (total // threshold) * threshold
            if current_milestone > last and current_milestone > 0:
                _last_milestone[guild.id] = current_milestone
                # Pass the real total, not the milestone
                await self._send_notification(guild, vc_cfg["channel_id"], total)
        else:
            # On leave, drop milestone so future joins re-trigger at the right point
            current_milestone = (total // threshold) * threshold
            if current_milestone < last:
                _last_milestone[guild.id] = current_milestone

    async def _send_notification(self, guild: discord.Guild, channel_id: int, total: int):
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return

        vc_cfg = _get_vc_config(guild.id)
        mention_everyone = vc_cfg.get("mention_everyone", False)

        embed = discord.Embed(
            description=f"**+{total}** en VC",
            color=0x2b2d31,
        )
        embed.set_footer(text=guild.name)

        try:
            content = "@everyone" if mention_everyone else None
            await channel.send(content=content, embed=embed)
        except discord.Forbidden:
            log.warning(f"[{guild.name}] No permission to send VC notification.")
        except Exception as e:
            log.error(f"[{guild.name}] VC notification error: {e}")

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.group(name="setvc", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def setvc(self, ctx: commands.Context):
        """VC tracker configuration."""
        await self._send_status(ctx)

    @setvc.command(name="status")
    @commands.has_permissions(manage_guild=True)
    async def setvc_status(self, ctx: commands.Context):
        """Show current VC tracker config."""
        await self._send_status(ctx)

    async def _send_status(self, ctx: commands.Context):
        vc_cfg = _get_vc_config(ctx.guild.id)
        channel_id = vc_cfg.get("channel_id")
        channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
        threshold = vc_cfg.get("threshold", 5)
        enabled = vc_cfg.get("enabled", False)
        total = _get_vc_total(ctx.guild)

        embed = discord.Embed(color=0x2b2d31)
        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None,
        )
        embed.add_field(name="Estado", value="`activo`" if enabled else "`inactivo`", inline=True)
        embed.add_field(name="Canal", value=channel.mention if channel else "`no configurado`", inline=True)
        embed.add_field(name="Umbral", value=f"`cada {threshold} personas`", inline=True)
        embed.add_field(name="@everyone", value="`on`" if vc_cfg.get("mention_everyone") else "`off`", inline=True)
        embed.add_field(name="En VC ahora", value=f"`{total} personas`", inline=True)
        await ctx.send(embed=embed)

    @setvc.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def setvc_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the notification channel. Example: ,setvc channel #canal"""
        vc_cfg = _get_vc_config(ctx.guild.id)
        vc_cfg["channel_id"] = channel.id
        vc_cfg["enabled"] = True
        _save_vc_config(ctx.guild.id, vc_cfg)

        await ctx.send(embed=discord.Embed(
            description=f"Canal de VC tracker configurado: {channel.mention}",
            color=0x57f287,
        ))

    @setvc.command(name="threshold")
    @commands.has_permissions(manage_guild=True)
    async def setvc_threshold(self, ctx: commands.Context, n: int):
        """Set notification threshold. Example: ,setvc threshold 10"""
        if n < 1:
            return await ctx.send(embed=discord.Embed(
                description="El umbral debe ser al menos `1`.",
                color=0xed4245,
            ))

        vc_cfg = _get_vc_config(ctx.guild.id)
        vc_cfg["threshold"] = n
        _save_vc_config(ctx.guild.id, vc_cfg)

        # Reset milestone so it recalculates with new threshold
        _last_milestone.pop(ctx.guild.id, None)

        await ctx.send(embed=discord.Embed(
            description=f"Umbral configurado: notifica cada `{n}` personas en VC.",
            color=0x57f287,
        ))

    @setvc.command(name="mention")
    @commands.has_permissions(manage_guild=True)
    async def setvc_mention(self, ctx: commands.Context, state: str):
        """Toggle @everyone mention on VC notifications. Example: ,setvc mention on"""
        state = state.lower()
        if state not in ("on", "off"):
            return await ctx.send(embed=discord.Embed(
                description="Usa `on` o `off`.",
                color=0xed4245,
            ))

        enabled = state == "on"
        vc_cfg = _get_vc_config(ctx.guild.id)
        vc_cfg["mention_everyone"] = enabled
        _save_vc_config(ctx.guild.id, vc_cfg)

        word = "activado" if enabled else "desactivado"
        color = 0x57f287 if enabled else 0xed4245
        await ctx.send(embed=discord.Embed(
            description=f"@everyone en notificaciones de VC **{word}**.",
            color=color,
        ))

    @setvc.command(name="off")
    @commands.has_permissions(manage_guild=True)
    async def setvc_off(self, ctx: commands.Context):
        """Disable VC tracker notifications."""
        vc_cfg = _get_vc_config(ctx.guild.id)
        vc_cfg["enabled"] = False
        _save_vc_config(ctx.guild.id, vc_cfg)
        _last_milestone.pop(ctx.guild.id, None)

        await ctx.send(embed=discord.Embed(
            description="VC tracker desactivado.",
            color=0xed4245,
        ))


    @commands.command(name="vc")
    @commands.has_permissions(manage_guild=True)
    async def vc_manual(self, ctx: commands.Context):
        """Manda manualmente el embed de VC con el total actual."""
        guild = ctx.guild
        vc_cfg = _get_vc_config(guild.id)

        if not vc_cfg.get("channel_id"):
            return await ctx.send(embed=discord.Embed(
                description="No hay canal de VC configurado. Usa `,setvc channel #canal` primero.",
                color=0xed4245,
            ))

        total = _get_vc_total(guild)
        await self._send_notification(guild, vc_cfg["channel_id"], total)

        # Si el comando se usó en un canal distinto al de vc, confirma
        if ctx.channel.id != vc_cfg["channel_id"]:
            channel = guild.get_channel(int(vc_cfg["channel_id"]))
            await ctx.send(embed=discord.Embed(
                description=f"Mensaje enviado a {channel.mention}.",
                color=0x2b2d31,
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(VCTracker(bot))
