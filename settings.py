"""
settings.py — Full configuration interface for the AntiNuke bot.

Commands:
  ,antinuke enable/disable
  ,antinuke status
  ,antinuke punishment <ban|kick|strip|mute>
  ,antinuke threshold <module> <number>
  ,antinuke window <module> <seconds>
  ,antinuke module <module> <on|off>
  ,antinuke accountage <days>
  ,antinuke guildage <days>
  ,setlogs <#channel>
  ,setprefix <prefix>
  ,logembed color <hex>
  ,logembed footer <text>
  ,logembed thumbnail <on|off>
"""

import discord
from discord.ext import commands
from config import db, default_guild_config
import logging

log = logging.getLogger("antinuke.settings")

MODULES = {
    "ban":            ("anti_ban",            "ban_threshold",            "ban_window"),
    "kick":           ("anti_kick",           "kick_threshold",           "kick_window"),
    "channeldelete":  ("anti_channel_delete", "channel_delete_threshold", "channel_delete_window"),
    "channelcreate":  ("anti_channel_create", "channel_create_threshold", "channel_create_window"),
    "roledelete":     ("anti_role_delete",    "role_delete_threshold",    "role_delete_window"),
    "rolecreate":     ("anti_role_create",    "role_create_threshold",    "role_create_window"),
    "webhook":        ("anti_webhook",        "webhook_create_threshold", "webhook_create_window"),
    "mention":        ("anti_mention",        "mention_threshold",        "mention_window"),
    "emojidelete":    ("anti_emoji_delete",   "emoji_delete_threshold",   "emoji_delete_window"),
    "botadd":         ("anti_bot_add",        None,                       None),
    "everyone":       ("anti_everyone_mention", None,                     None),
    "serverupdate":   ("anti_server_update",  None,                       None),
    "prune":          ("anti_prune",          None,                       None),
}

PUNISHMENT_CHOICES = ("ban", "kick", "strip", "mute")


def is_manager():
    async def predicate(ctx):
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return False
    return commands.check(predicate)


def build_embed(guild, desc, color=0x2b2d31):
    e = discord.Embed(description=desc, color=color)
    e.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    return e


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── ,antinuke group ───────────────────────────────────────────────────────

    @commands.group(name="antinuke", aliases=["an"], invoke_without_command=True)
    @is_manager()
    async def antinuke(self, ctx):
        """Show current AntiNuke configuration."""
        await self.antinuke_status(ctx)

    @antinuke.command(name="enable")
    @is_manager()
    async def antinuke_enable(self, ctx):
        """Enable AntiNuke protection."""
        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["enabled"] = True
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(ctx.guild, "AntiNuke protection has been **enabled**.", 0x57f287))

    @antinuke.command(name="disable")
    @is_manager()
    async def antinuke_disable(self, ctx):
        """Disable AntiNuke protection."""
        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["enabled"] = False
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(ctx.guild, "AntiNuke protection has been **disabled**.", 0xed4245))

    @antinuke.command(name="status")
    @is_manager()
    async def antinuke_status(self, ctx):
        """Display full AntiNuke configuration."""
        config = db.get_guild(ctx.guild.id)
        an = config["antinuke"]

        enabled_str = "**Enabled**" if an.get("enabled") else "**Disabled**"
        punishment = an.get("punishment", "ban").capitalize()
        wl_count = len(config.get("whitelist", []))
        log_ch = config.get("log_channel")
        log_str = f"<#{log_ch}>" if log_ch else "`Not set`"
        min_age = an.get("min_account_age_days", 0)
        guild_age = an.get("min_guild_age_days", 0)

        def toggle(key):
            return "` on `" if an.get(key, True) else "`off`"

        e = discord.Embed(title="AntiNuke Configuration", color=0x2b2d31)
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)

        e.add_field(name="Status", value=enabled_str, inline=True)
        e.add_field(name="Punishment", value=f"`{punishment}`", inline=True)
        e.add_field(name="Log Channel", value=log_str, inline=True)
        e.add_field(name="Whitelist", value=f"`{wl_count} users`", inline=True)
        e.add_field(name="Min Account Age", value=f"`{min_age} days`" if min_age else "`disabled`", inline=True)
        e.add_field(name="Min Guild Age", value=f"`{guild_age} days`" if guild_age else "`disabled`", inline=True)

        modules_text = (
            f"Anti-Ban {toggle('anti_ban')}  "
            f"Anti-Kick {toggle('anti_kick')}  "
            f"Channel Delete {toggle('anti_channel_delete')}  "
            f"Channel Create {toggle('anti_channel_create')}\n"
            f"Role Delete {toggle('anti_role_delete')}  "
            f"Role Create {toggle('anti_role_create')}  "
            f"Webhook {toggle('anti_webhook')}  "
            f"Mention {toggle('anti_mention')}\n"
            f"Emoji Delete {toggle('anti_emoji_delete')}  "
            f"Bot Add {toggle('anti_bot_add')}  "
            f"Everyone {toggle('anti_everyone_mention')}  "
            f"Server Update {toggle('anti_server_update')}\n"
            f"Prune {toggle('anti_prune')}"
        )
        e.add_field(name="Modules", value=modules_text, inline=False)

        thresholds = (
            f"Ban: `{an.get('ban_threshold',3)}/{an.get('ban_window',10)}s`  "
            f"Kick: `{an.get('kick_threshold',3)}/{an.get('kick_window',10)}s`  "
            f"Ch.Del: `{an.get('channel_delete_threshold',3)}/{an.get('channel_delete_window',10)}s`\n"
            f"Ch.Create: `{an.get('channel_create_threshold',3)}/{an.get('channel_create_window',10)}s`  "
            f"Role.Del: `{an.get('role_delete_threshold',3)}/{an.get('role_delete_window',10)}s`  "
            f"Role.Create: `{an.get('role_create_threshold',3)}/{an.get('role_create_window',10)}s`\n"
            f"Webhook: `{an.get('webhook_create_threshold',3)}/{an.get('webhook_create_window',10)}s`  "
            f"Mentions: `{an.get('mention_threshold',10)}/{an.get('mention_window',8)}s`  "
            f"Emoji.Del: `{an.get('emoji_delete_threshold',5)}/{an.get('emoji_delete_window',10)}s`"
        )
        e.add_field(name="Thresholds (amount/window)", value=thresholds, inline=False)
        e.set_footer(text="Use ,antinuke threshold <module> <n> to change values")
        await ctx.send(embed=e)

    @antinuke.command(name="punishment", aliases=["punish", "action"])
    @is_manager()
    async def antinuke_punishment(self, ctx, punishment: str):
        """Set punishment type: ban, kick, strip, mute."""
        punishment = punishment.lower()
        if punishment not in PUNISHMENT_CHOICES:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Invalid punishment. Choose from: {', '.join(f'`{p}`' for p in PUNISHMENT_CHOICES)}"
            ))
        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["punishment"] = punishment
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(
            ctx.guild, f"Punishment set to `{punishment}`.", 0x57f287
        ))

    @antinuke.command(name="threshold", aliases=["thresh"])
    @is_manager()
    async def antinuke_threshold(self, ctx, module: str, amount: int):
        """
        Set action threshold for a module.
        Modules: ban, kick, channeldelete, channelcreate, roledelete,
                 rolecreate, webhook, mention, emojidelete
        """
        module = module.lower()
        if module not in MODULES:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Unknown module `{module}`. Available: {', '.join(f'`{m}`' for m in MODULES)}"
            ))
        _, threshold_key, _ = MODULES[module]
        if threshold_key is None:
            return await ctx.send(embed=build_embed(
                ctx.guild, f"Module `{module}` does not have a configurable threshold."
            ))
        if amount < 1:
            return await ctx.send(embed=build_embed(ctx.guild, "Threshold must be at least 1."))
        config = db.get_guild(ctx.guild.id)
        config["antinuke"][threshold_key] = amount
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(
            ctx.guild, f"Threshold for `{module}` set to `{amount}`.", 0x57f287
        ))

    @antinuke.command(name="window")
    @is_manager()
    async def antinuke_window(self, ctx, module: str, seconds: int):
        """
        Set time window (in seconds) for a module's rate-limit.
        """
        module = module.lower()
        if module not in MODULES:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Unknown module `{module}`. Available: {', '.join(f'`{m}`' for m in MODULES)}"
            ))
        _, _, window_key = MODULES[module]
        if window_key is None:
            return await ctx.send(embed=build_embed(
                ctx.guild, f"Module `{module}` does not have a configurable window."
            ))
        if seconds < 1 or seconds > 3600:
            return await ctx.send(embed=build_embed(ctx.guild, "Window must be between 1 and 3600 seconds."))
        config = db.get_guild(ctx.guild.id)
        config["antinuke"][window_key] = seconds
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(
            ctx.guild, f"Window for `{module}` set to `{seconds}s`.", 0x57f287
        ))

    @antinuke.command(name="module")
    @is_manager()
    async def antinuke_module(self, ctx, module: str, state: str):
        """Toggle a specific module on or off."""
        module = module.lower()
        if module not in MODULES:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Unknown module `{module}`. Available: {', '.join(f'`{m}`' for m in MODULES)}"
            ))
        state = state.lower()
        if state not in ("on", "off", "enable", "disable", "true", "false", "1", "0"):
            return await ctx.send(embed=build_embed(ctx.guild, "State must be `on` or `off`."))
        enabled = state in ("on", "enable", "true", "1")
        toggle_key, _, _ = MODULES[module]
        config = db.get_guild(ctx.guild.id)
        config["antinuke"][toggle_key] = enabled
        db.update_guild(ctx.guild.id, config)
        word = "enabled" if enabled else "disabled"
        color = 0x57f287 if enabled else 0xed4245
        await ctx.send(embed=build_embed(ctx.guild, f"Module `{module}` has been **{word}**.", color))

    @antinuke.command(name="accountage", aliases=["acctage"])
    @is_manager()
    async def antinuke_accountage(self, ctx, days: int):
        """
        Set minimum account age in days to join.
        Set to 0 to disable.
        """
        if days < 0:
            return await ctx.send(embed=build_embed(ctx.guild, "Days must be 0 or more. Use 0 to disable."))
        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["min_account_age_days"] = days
        db.update_guild(ctx.guild.id, config)
        msg = f"Minimum account age set to `{days} days`." if days else "Minimum account age check **disabled**."
        await ctx.send(embed=build_embed(ctx.guild, msg, 0x57f287))

    @antinuke.command(name="guildage")
    @is_manager()
    async def antinuke_guildage(self, ctx, days: int):
        """
        Set minimum days a member must have been in the guild before executing sensitive actions.
        Set to 0 to disable.
        """
        if days < 0:
            return await ctx.send(embed=build_embed(ctx.guild, "Days must be 0 or more. Use 0 to disable."))
        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["min_guild_age_days"] = days
        db.update_guild(ctx.guild.id, config)
        msg = f"Minimum guild age set to `{days} days`." if days else "Minimum guild age check **disabled**."
        await ctx.send(embed=build_embed(ctx.guild, msg, 0x57f287))

    @antinuke.command(name="reset")
    @commands.is_owner()
    async def antinuke_reset(self, ctx):
        """Reset AntiNuke config to defaults. (Bot owner only)"""
        config = db.get_guild(ctx.guild.id)
        config["antinuke"] = default_guild_config()["antinuke"]
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(ctx.guild, "AntiNuke configuration reset to defaults.", 0xfee75c))

    # ── ,setlogs ──────────────────────────────────────────────────────────────

    @commands.command(name="setlogs", aliases=["logchannel", "logs"])
    @is_manager()
    async def set_logs(self, ctx, channel: discord.TextChannel = None):
        """Set the log channel for AntiNuke events."""
        config = db.get_guild(ctx.guild.id)
        if channel is None:
            config["log_channel"] = None
            db.update_guild(ctx.guild.id, config)
            return await ctx.send(embed=build_embed(ctx.guild, "Log channel cleared.", 0xed4245))
        config["log_channel"] = channel.id
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(ctx.guild, f"Log channel set to {channel.mention}.", 0x57f287))

    # ── ,setprefix ────────────────────────────────────────────────────────────

    @commands.command(name="setprefix", aliases=["prefix"])
    @is_manager()
    async def set_prefix(self, ctx, *, prefix: str):
        """Change the bot prefix for this server."""
        if len(prefix) > 5:
            return await ctx.send(embed=build_embed(ctx.guild, "Prefix must be 5 characters or fewer."))
        config = db.get_guild(ctx.guild.id)
        config["prefix"] = prefix
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(
            ctx.guild, f"Prefix updated to `{prefix}`", 0x57f287
        ))

    # ── ,logembed ─────────────────────────────────────────────────────────────

    @commands.group(name="logembed", invoke_without_command=True)
    @is_manager()
    async def logembed(self, ctx):
        """Customize the appearance of log embeds. Subcommands: color, footer, thumbnail."""
        config = db.get_guild(ctx.guild.id)
        emb = config.get("log_embed", {})
        color = emb.get("color", 0x2b2d31)
        footer = emb.get("footer_text", "AntiNuke Protection")
        thumb = emb.get("thumbnail", True)
        e = discord.Embed(title="Log Embed Settings", color=color)
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        e.add_field(name="Color", value=f"`#{color:06x}`", inline=True)
        e.add_field(name="Footer", value=f"`{footer}`", inline=True)
        e.add_field(name="Thumbnail", value="`on`" if thumb else "`off`", inline=True)
        await ctx.send(embed=e)

    @logembed.command(name="color")
    @is_manager()
    async def logembed_color(self, ctx, hex_color: str):
        """
        Set the color of log embeds.
        Example: ,logembed color #ff0000  or  ,logembed color ff0000
        You can use your server's color or any hex.
        """
        hex_color = hex_color.lstrip("#")
        try:
            color_int = int(hex_color, 16)
        except ValueError:
            return await ctx.send(embed=build_embed(ctx.guild, "Invalid hex color. Example: `#ff0000`"))
        config = db.get_guild(ctx.guild.id)
        if "log_embed" not in config:
            config["log_embed"] = {}
        config["log_embed"]["color"] = color_int
        db.update_guild(ctx.guild.id, config)
        e = discord.Embed(description=f"Log embed color set to `#{hex_color.upper()}`.", color=color_int)
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.send(embed=e)

    @logembed.command(name="footer")
    @is_manager()
    async def logembed_footer(self, ctx, *, text: str):
        """
        Set the footer text for log embeds.
        You can use custom text or server emojis (paste the emoji directly).
        Example: ,logembed footer :shield: MyServer Protection
        """
        if len(text) > 100:
            return await ctx.send(embed=build_embed(ctx.guild, "Footer text must be 100 characters or fewer."))
        config = db.get_guild(ctx.guild.id)
        if "log_embed" not in config:
            config["log_embed"] = {}
        config["log_embed"]["footer_text"] = text
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(ctx.guild, f"Footer text updated to: `{text}`", 0x57f287))

    @logembed.command(name="thumbnail")
    @is_manager()
    async def logembed_thumbnail(self, ctx, state: str):
        """Toggle server icon thumbnail in log embeds: on or off."""
        state = state.lower()
        if state not in ("on", "off"):
            return await ctx.send(embed=build_embed(ctx.guild, "Use `on` or `off`."))
        enabled = state == "on"
        config = db.get_guild(ctx.guild.id)
        if "log_embed" not in config:
            config["log_embed"] = {}
        config["log_embed"]["thumbnail"] = enabled
        db.update_guild(ctx.guild.id, config)
        word = "enabled" if enabled else "disabled"
        await ctx.send(embed=build_embed(ctx.guild, f"Log embed thumbnail **{word}**.", 0x57f287))


    # ── ,status ───────────────────────────────────────────────────────────────

    @commands.group(name="status", invoke_without_command=True)
    @commands.is_owner()
    async def status_cmd(self, ctx, activity_type: str = None, *, text: str = None):
        """
        Change the bot's status and activity. (Bot owner only)

        Activity types: watching, playing, listening, competing
        Examples:
          ,status watching 100 servers
          ,status playing algo
          ,status listening música
          ,status dnd
          ,status online
          ,status idle
          ,status invisible
          ,status clear        — removes activity
        """
        if activity_type is None:
            return await ctx.send(embed=discord.Embed(
                description=(
                    "**,status** — cambia el status del bot.\n\n"
                    "`,status watching <texto>`\n"
                    "`,status playing <texto>`\n"
                    "`,status listening <texto>`\n"
                    "`,status competing <texto>`\n"
                    "`,status online` · `dnd` · `idle` · `invisible`\n"
                    "`,status clear` — quita la actividad"
                ),
                color=0x2b2d31,
            ))

        activity_type = activity_type.lower()

        # ── Status only (no activity text) ────────────────────────────────────
        status_map = {
            "online":    discord.Status.online,
            "dnd":       discord.Status.dnd,
            "idle":      discord.Status.idle,
            "invisible": discord.Status.invisible,
        }
        if activity_type in status_map:
            await self.bot.change_presence(status=status_map[activity_type])
            return await ctx.send(embed=discord.Embed(
                description=f"Status cambiado a `{activity_type}`.",
                color=0x57f287,
            ))

        # ── Clear activity ────────────────────────────────────────────────────
        if activity_type == "clear":
            await self.bot.change_presence(activity=None)
            return await ctx.send(embed=discord.Embed(
                description="Actividad removida.",
                color=0x57f287,
            ))

        # ── Activity types ────────────────────────────────────────────────────
        if not text:
            return await ctx.send(embed=discord.Embed(
                description=f"Falta el texto. Ejemplo: `,status {activity_type} tu texto aquí`",
                color=0xed4245,
            ))

        activity_type_map = {
            "watching":   discord.ActivityType.watching,
            "playing":    discord.ActivityType.playing,
            "listening":  discord.ActivityType.listening,
            "competing":  discord.ActivityType.competing,
        }
        if activity_type not in activity_type_map:
            return await ctx.send(embed=discord.Embed(
                description=(
                    f"Tipo inválido `{activity_type}`.\n"
                    "Usa: `watching` · `playing` · `listening` · `competing`"
                ),
                color=0xed4245,
            ))

        activity = discord.Activity(
            type=activity_type_map[activity_type],
            name=text,
        )
        await self.bot.change_presence(activity=activity)
        await ctx.send(embed=discord.Embed(
            description=f"Actividad: `{activity_type} {text}`",
            color=0x57f287,
        ))


async def setup(bot):
    await bot.add_cog(Settings(bot))
