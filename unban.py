"""
unban.py — Mass unban con notificación por DM.

Comando:
  ,unbanall   — desbanea a todos los usuarios baneados del servidor y les manda un DM avisando
"""

import discord
from discord.ext import commands
import asyncio
import logging

log = logging.getLogger("antinuke.unban")

INVITE_LINK = "https://discord.gg/parchados"


class Unban(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="unbanall")
    @commands.has_permissions(ban_members=True)
    async def unban_all(self, ctx: commands.Context):
        guild = ctx.guild

        msg = await ctx.send(embed=discord.Embed(
            description="Buscando usuarios baneados...",
            color=0x2b2d31,
        ))

        bans = [entry async for entry in guild.bans()]

        if not bans:
            return await msg.edit(embed=discord.Embed(
                description="No hay usuarios baneados en este servidor.",
                color=0x2b2d31,
            ))

        await msg.edit(embed=discord.Embed(
            description=f"Desbaneando a `{len(bans)}` usuario(s)...",
            color=0x2b2d31,
        ))

        unbanned = 0
        dm_sent = 0

        for entry in bans:
            user = entry.user

            try:
                await user.send(embed=discord.Embed(
                    description=(
                        f"Has sido desbaneado de **{guild.name}**.\n"
                        f"Puedes volver a unirte aquí: {INVITE_LINK}"
                    ),
                    color=0x57f287,
                ))
                dm_sent += 1
            except (discord.Forbidden, discord.HTTPException):
                pass

            try:
                await guild.unban(user, reason=f"Unban all por {ctx.author}")
                unbanned += 1
            except discord.Forbidden:
                log.warning(f"[{guild.name}] Sin permisos para desbanear a {user}")
            except discord.HTTPException as e:
                log.error(f"[{guild.name}] Error desbaneando a {user}: {e}")

            await asyncio.sleep(0.5)  # rate-limit guard

        await msg.edit(embed=discord.Embed(
            description=(
                f"Listo. `{unbanned}/{len(bans)}` usuarios desbaneados.\n"
                f"`{dm_sent}` recibieron el DM de aviso."
            ),
            color=0x57f287,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Unban(bot))
