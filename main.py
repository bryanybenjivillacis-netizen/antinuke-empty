import discord
from discord.ext import commands
import asyncio
import os
import logging
from config import db, DEFAULT_PREFIX

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("antinuke")


class AntiNukeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix=self.get_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            owner_ids=self._load_owners(),
        )
        self.db = db

    def _load_owners(self):
        owners = os.getenv("OWNER_IDS", "")
        if not owners:
            return set()
        return set(int(x.strip()) for x in owners.split(",") if x.strip().isdigit())

    async def get_prefix(self, message):
        if not message.guild:
            return [","]
        guild_data = db.get_guild(message.guild.id)
        prefix = guild_data.get("prefix", DEFAULT_PREFIX)
        return commands.when_mentioned_or(prefix)(self, message)

    async def setup_hook(self):
        cogs = [
            "backup",
            "antinuke",
            "whitelist",
            "settings",
            "vc_tracker",
            "welcome",
            "invites",
            "giveaway",
            "help",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                import traceback
                log.error(f"Failed to load {cog}:\n{traceback.format_exc()}")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} ({self.user.id})")
        await self.change_presence(
            status=discord.Status.dnd,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | ,help"
            )
        )

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=discord.Embed(
                description="No tienes permisos suficientes.",
                color=0x2b2d31
            ))
        elif isinstance(error, commands.NotOwner):
            await ctx.send(embed=discord.Embed(
                description="Este comando es solo para el owner.",
                color=0x2b2d31
            ))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(
                description=f"Argumento faltante: `{error.param.name}`",
                color=0x2b2d31
            ))
        else:
            log.error(f"Error en {ctx.command}: {error}")


async def main():
    token = os.getenv("TOKEN")
    if not token:
        log.critical("TOKEN environment variable not set.")
        return
    bot = AntiNukeBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
