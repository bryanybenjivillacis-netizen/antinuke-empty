"""
vc_tracker.py — Real-time voice channel population tracker.

Commands:
  ,setvc channel #canal   — configura canal de notificaciones automáticas
  ,setvc threshold <n>    — cada cuántas personas notifica (default 5)
  ,vcstats                — manda embed con total exacto en VC (manage_guild)
"""

import discord
from discord.ext import commands
from config import db
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("antinuke.vc_tracker")

# In-memory: guild_id → last notified milestone
_last_milestone: dict[int, int] = {}
_last_sent: dict[int, datetime] = {}  # guild_id → última vez que se mandó notif

# In-memory: channel_id → webhook usado para las notificaciones automáticas
_webhook_cache: dict[int, discord.Webhook] = {}

# Banner del bot (se obtiene una sola vez y se cachea)
_bot_banner_url: str | None = None
_bot_banner_fetched = False

WEBHOOK_NAME = "Status Tussi"


def _get_vc_total(guild: discord.Guild) -> int:
    """Count total non-bot users across all voice channels."""
    total = 0
    for vc in guild.voice_channels:
        for member in vc.members:
            if not member.bot:
                total += 1
    return total


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


def _build_embed(total: int, guild: discord.Guild, banner_url: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        description=f"**+{total}** en VC",
        color=0x2b2d31,
    )
    embed.set_footer(text=guild.name)
    if banner_url:
        embed.set_image(url=banner_url)
    return embed


async def _get_bot_banner_url(bot: commands.Bot) -> str | None:
    """Obtiene el banner del bot una sola vez (se cachea en memoria)."""
    global _bot_banner_url, _bot_banner_fetched
    if not _bot_banner_fetched:
        _bot_banner_fetched = True
        try:
            full_user = await bot.fetch_user(bot.user.id)
            if full_user.banner:
                _bot_banner_url = full_user.banner.url
        except Exception as e:
            log.warning(f"No se pudo obtener el banner del bot: {e}")
    return _bot_banner_url


async def _get_vc_webhook(channel: discord.TextChannel) -> discord.Webhook | None:
    """Busca o crea el webhook 'Status Tussi' en el canal, y lo cachea."""
    if channel.id in _webhook_cache:
        return _webhook_cache[channel.id]
    try:
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name=WEBHOOK_NAME)
        if webhook is None:
            webhook = await channel.create_webhook(name=WEBHOOK_NAME)
        _webhook_cache[channel.id] = webhook
        return webhook
    except discord.Forbidden:
        log.warning(f"No permission to manage webhooks in #{channel.name}")
        return None
    except Exception as e:
        log.error(f"Error creating VC webhook: {e}")
        return None


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

                # Cooldown: no enviar más de una vez cada 12 minutos
                last_sent = _last_sent.get(guild.id)
                if last_sent and (datetime.now(timezone.utc) - last_sent).total_seconds() < 720:
                    return
                _last_sent[guild.id] = datetime.now(timezone.utc)

                channel = guild.get_channel(int(vc_cfg["channel_id"]))
                if channel:
                    try:
                        banner_url = await _get_bot_banner_url(self.bot)
                        embed = _build_embed(total, guild, banner_url)
                        webhook = await _get_vc_webhook(channel)
                        if webhook:
                            await webhook.send(
                                embed=embed,
                                username=WEBHOOK_NAME,
                                avatar_url=self.bot.user.display_avatar.url,
                            )
                        else:
                            await channel.send(embed=embed)
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
        await ctx.send(embed=discord.Embed(
            description="Usa `,setvc channel #canal` o `,setvc threshold <número>`.",
            color=0x2b2d31,
        ))

    @setvc.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def setvc_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Ejemplo: ,setvc channel #canal"""
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
        """Ejemplo: ,setvc threshold 10"""
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
        try:
            total = _get_vc_total(ctx.guild)
            await ctx.send(embed=_build_embed(total, ctx.guild))
        except Exception as e:
            log.error(f"[{ctx.guild.name}] vcstats error: {e}")
            await ctx.send(embed=discord.Embed(
                description=f"Error: `{e}`",
                color=0xed4245,
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(VCTracker(bot))
