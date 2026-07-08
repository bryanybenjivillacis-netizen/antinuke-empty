import discord
from discord.ext import commands
from config import db
import logging

log = logging.getLogger("antinuke.help")

# ── Command reference table ───────────────────────────────────────────────────

CATEGORIES = {
    "AntiNuke": {
        "description": "Core protection engine — enable, disable, and tune every module.",
        "commands": [
            (",antinuke enable", "Activate protection on this server"),
            (",antinuke disable", "Deactivate protection on this server"),
            (",antinuke status", "Show full configuration overview"),
            (",antinuke punishment <type>", "Set response action: `ban` `kick` `strip` `mute`"),
            (",antinuke module <name> <on/off>", "Toggle a specific module"),
            (",antinuke threshold <module> <n>", "How many actions before triggering (per window)"),
            (",antinuke window <module> <sec>", "Time window in seconds for the rate-limit"),
            (",antinuke accountage <days>", "Min account age to join (0 = disabled)"),
            (",antinuke guildage <days>", "Min days in guild before actions are trusted (0 = off)"),
            (",antinuke reset", "Reset config to defaults *(bot owner)*"),
        ],
    },
    "Modules": {
        "description": "Available protection modules that can be toggled independently.",
        "commands": [
            ("ban", "Detects mass ban attacks"),
            ("kick", "Detects mass kick attacks"),
            ("channeldelete", "Detects channel mass deletion"),
            ("channelcreate", "Detects channel spam creation"),
            ("roledelete", "Detects role mass deletion"),
            ("rolecreate", "Detects role spam creation"),
            ("webhook", "Detects unauthorized webhook creation"),
            ("mention", "Detects mention spam / mass pings"),
            ("emojidelete", "Detects bulk emoji deletion"),
            ("botadd", "Blocks unauthorized bot additions"),
            ("everyone", "Blocks unauthorized @everyone/@here mentions"),
            ("serverupdate", "Blocks unauthorized server name/icon changes"),
            ("prune", "Blocks unauthorized member prunes"),
        ],
    },
    "Whitelist": {
        "description": "Users on the whitelist are completely exempt from AntiNuke detection.",
        "commands": [
            (",whitelist", "Show whitelisted users"),
            (",whitelist add <user>","Add a user to the whitelist *(owner only)*"),
            (",whitelist remove <user>","Remove a user from the whitelist *(owner only)*"),
            (",whitelist clear", "Remove everyone from the whitelist *(owner only)*"),
            (",whitelist check <user>","Check if a user is whitelisted"),
        ],
    },
    "Logs & Settings": {
        "description": "Configure log channels, prefixes, and embed appearance.",
        "commands": [
            (",setlogs [#channel]", "Set log channel (omit to clear)"),
            (",setprefix <prefix>", "Change the command prefix"),
            (",logembed color <hex>", "Change log embed color (e.g. `#a855f7`)"),
            (",logembed footer <text>", "Set footer text (supports server emojis)"),
            (",logembed thumbnail <on/off>","Toggle server icon thumbnail in logs"),
        ],
    },
    "VC Tracker": {
        "description": "Tracks how many people are in voice channels and announces milestones.",
        "commands": [
            (",setvc channel <#channel>", "Set where automatic VC alerts are sent"),
            (",setvc threshold <n>", "Announce every time the VC count crosses a multiple of n"),
            (",vcstats", "Show the current number of people in voice channels right now"),
        ],
    },
}


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h", "commands"])
    async def help_command(self, ctx, *, category: str = None):
        """Show help for all commands or a specific category."""
        config = db.get_guild(ctx.guild.id)
        prefix = config.get("prefix", ",")

        if category is None:
            await self._send_overview(ctx, prefix)
        else:
            await self._send_category(ctx, prefix, category)

    async def _send_overview(self, ctx, prefix):
        guild = ctx.guild
        e = discord.Embed(
            description=(
                "**AntiNuke** — professional server protection.\n"
                f"Use `{prefix}help <category>` to see detailed commands.\n\u200b"
            ),
            color=0x2b2d31,
        )
        e.set_author(
            name=guild.name,
            icon_url=guild.icon.url if guild.icon else None,
        )
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        for name, data in CATEGORIES.items():
            count = len(data["commands"])
            e.add_field(
                name=f"{name} — `{count} commands`",
                value=data["description"],
                inline=False,
            )

        e.add_field(
            name="\u200b",
            value=(
                f"`{prefix}help antinuke` · `{prefix}help modules` · "
                f"`{prefix}help whitelist` · `{prefix}help logs` · `{prefix}help vc`"
            ),
            inline=False,
        )
        e.set_footer(text=f"Prefix: {prefix} · All times UTC")
        await ctx.send(embed=e)

    async def _send_category(self, ctx, prefix, category: str):
        guild = ctx.guild
        cat_key = None
        category_lower = category.lower()

        for key in CATEGORIES:
            if category_lower in key.lower() or category_lower in ["log", "logs", "settings"] and key == "Logs & Settings":
                cat_key = key
                break
            if category_lower in ["vc", "vctracker", "voice", "voicechannel"] and key == "VC Tracker":
                cat_key = key
                break

        if cat_key is None:
            e = discord.Embed(
                description=(
                    f"Category `{category}` not found.\n"
                    f"Available: `antinuke` · `modules` · `whitelist` · `logs` · `vc`"
                ),
                color=0x2b2d31,
            )
            e.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
            return await ctx.send(embed=e)

        data = CATEGORIES[cat_key]
        e = discord.Embed(
            title=cat_key,
            description=data["description"] + "\n\u200b",
            color=0x2b2d31,
        )
        e.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        lines = []
        for cmd, desc in data["commands"]:
            lines.append(f"`{cmd}`\n{desc}")

        # split into two columns if long
        half = (len(lines) + 1) // 2
        left = "\n\n".join(lines[:half])
        right = "\n\n".join(lines[half:])

        if right:
            e.add_field(name="\u200b", value=left, inline=True)
            e.add_field(name="\u200b", value=right, inline=True)
        else:
            e.add_field(name="\u200b", value=left, inline=False)

        e.set_footer(text=f"Prefix: {prefix} · <required> [optional]")
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Help(bot))
