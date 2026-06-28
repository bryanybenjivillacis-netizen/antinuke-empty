import discord
from discord.ext import commands
from config import db
import logging

log = logging.getLogger("antinuke.whitelist")


def is_guild_owner():
    async def predicate(ctx: commands.Context):
        return ctx.author.id == ctx.guild.owner_id or await ctx.bot.is_owner(ctx.author)
    return commands.check(predicate)


def is_manager():
    """Guild owner, bot owner, or admin."""
    async def predicate(ctx: commands.Context):
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return False
    return commands.check(predicate)


def build_embed(guild: discord.Guild, description: str, color: int = 0x2b2d31) -> discord.Embed:
    e = discord.Embed(description=description, color=color)
    e.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    return e


class Whitelist(commands.Cog):
    """Manage who is exempt from AntiNuke detection."""

    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="whitelist", aliases=["wl"], invoke_without_command=True)
    @is_manager()
    async def whitelist(self, ctx: commands.Context):
        """Whitelist management. Use subcommands: add, remove, list, clear."""
        config = db.get_guild(ctx.guild.id)
        wl = config.get("whitelist", [])

        if not wl:
            desc = "No users are whitelisted."
        else:
            lines = []
            for uid in wl:
                member = ctx.guild.get_member(uid)
                label = f"`{member}` (`{uid}`)" if member else f"`Unknown` (`{uid}`)"
                lines.append(f"**·** {label}")
            desc = "\n".join(lines)

        e = discord.Embed(
            title="Whitelist",
            description=desc,
            color=0x2b2d31
        )
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        e.set_footer(text=f"{len(wl)} user(s) whitelisted")
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=e)

    @whitelist.command(name="add")
    @is_guild_owner()
    async def whitelist_add(self, ctx: commands.Context, user: discord.Member):
        """Add a user to the whitelist."""
        config = db.get_guild(ctx.guild.id)
        wl: list = config.get("whitelist", [])

        if user.id in wl:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"`{user}` is already whitelisted.",
                0x2b2d31
            ))

        wl.append(user.id)
        config["whitelist"] = wl
        db.update_guild(ctx.guild.id, config)

        await ctx.send(embed=build_embed(
            ctx.guild,
            f"`{user}` has been added to the whitelist.",
            0x57f287
        ))
        log.info(f"[{ctx.guild.name}] {ctx.author} whitelisted {user}")

    @whitelist.command(name="remove", aliases=["rm", "del"])
    @is_guild_owner()
    async def whitelist_remove(self, ctx: commands.Context, user: discord.Member):
        """Remove a user from the whitelist."""
        config = db.get_guild(ctx.guild.id)
        wl: list = config.get("whitelist", [])

        if user.id not in wl:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"`{user}` is not whitelisted.",
                0x2b2d31
            ))

        wl.remove(user.id)
        config["whitelist"] = wl
        db.update_guild(ctx.guild.id, config)

        await ctx.send(embed=build_embed(
            ctx.guild,
            f"`{user}` has been removed from the whitelist.",
            0xed4245
        ))
        log.info(f"[{ctx.guild.name}] {ctx.author} removed {user} from whitelist")

    @whitelist.command(name="clear")
    @is_guild_owner()
    async def whitelist_clear(self, ctx: commands.Context):
        """Remove all users from the whitelist. (Owner only)"""
        config = db.get_guild(ctx.guild.id)
        count = len(config.get("whitelist", []))
        config["whitelist"] = []
        db.update_guild(ctx.guild.id, config)

        await ctx.send(embed=build_embed(
            ctx.guild,
            f"Whitelist cleared. `{count}` user(s) removed.",
            0xed4245
        ))

    @whitelist.command(name="check")
    @is_manager()
    async def whitelist_check(self, ctx: commands.Context, user: discord.Member):
        """Check if a user is whitelisted."""
        config = db.get_guild(ctx.guild.id)
        wl = config.get("whitelist", [])
        status = "whitelisted" if user.id in wl else "**not** whitelisted"
        await ctx.send(embed=build_embed(
            ctx.guild,
            f"`{user}` is {status}."
        ))


async def setup(bot):
    await bot.add_cog(Whitelist(bot))
