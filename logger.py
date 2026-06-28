import discord
from datetime import datetime, timezone
from config import db
import logging

log = logging.getLogger("antinuke.logger")

PUNISHMENT_LABELS = {
    "ban": "Banned",
    "kick": "Kicked",
    "strip": "Roles Stripped",
    "mute": "Server Muted",
}


async def send_log(
    guild: discord.Guild,
    *,
    action: str,
    target: discord.Member | discord.User | None,
    moderator: discord.Member | discord.User | None,
    reason: str,
    module: str,
    extra_fields: list[tuple] | None = None,
    color: int | None = None,
):
    """
    Send a professional log embed to the guild's log channel.
    """
    config = db.get_guild(guild.id)
    log_channel_id = config.get("log_channel")
    if not log_channel_id:
        return

    channel = guild.get_channel(int(log_channel_id))
    if not channel:
        return

    embed_cfg = config.get("log_embed", {})
    embed_color = color or embed_cfg.get("color", 0x2b2d31)
    footer_text = embed_cfg.get("footer_text", "AntiNuke Protection")
    show_thumbnail = embed_cfg.get("thumbnail", True)

    punishment = config["antinuke"].get("punishment", "ban")
    punishment_label = PUNISHMENT_LABELS.get(punishment, punishment.capitalize())

    now = datetime.now(timezone.utc)
    timestamp_str = f"<t:{int(now.timestamp())}:F>"

    embed = discord.Embed(color=embed_color, timestamp=now)
    embed.set_author(
        name=guild.name,
        icon_url=guild.icon.url if guild.icon else None
    )

    # Title line
    embed.title = f"AntiNuke — {module}"

    # Moderator / Punished user
    if target:
        embed.add_field(
            name="Offender",
            value=f"{target.mention} `{target}` (`{target.id}`)",
            inline=False
        )
    if moderator:
        embed.add_field(
            name="Actioned By",
            value=f"{moderator.mention} `{moderator}` (`{moderator.id}`)",
            inline=False
        )

    embed.add_field(name="Action Taken", value=f"`{punishment_label}`", inline=True)
    embed.add_field(name="Module", value=f"`{module}`", inline=True)
    embed.add_field(name="Triggered At", value=timestamp_str, inline=False)
    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

    if extra_fields:
        for name, value, inline in extra_fields:
            embed.add_field(name=name, value=value, inline=inline)

    if show_thumbnail and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.set_footer(text=footer_text)

    try:
        await channel.send(embed=embed)
    except Exception as e:
        log.warning(f"Failed to send log embed in {guild.name}: {e}")
