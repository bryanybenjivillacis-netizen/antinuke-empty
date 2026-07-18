"""
lockdown.py — Bloqueo/ocultamiento masivo de canales (server lockdown).

Comandos:
  ,lockdown                         — oculta y cierra todos los canales (excepto los exentos)
  ,unlock                           — restaura los canales a como estaban antes del lockdown
  ,lockdown exempt add <#canal>     — agrega un canal a la lista de exentos (no se toca)
  ,lockdown exempt remove <#canal>  — quita un canal de la lista de exentos
  ,lockdown exempt list             — muestra los canales exentos
"""

from typing import Union
import discord
from discord.ext import commands
from config import db


def _get_exempt(guild_id: int) -> list:
    config = db.get_guild(guild_id)
    return config.get("lockdown_exempt", [])


def _save_exempt(guild_id: int, ids: list):
    config = db.get_guild(guild_id)
    config["lockdown_exempt"] = ids
    db.update_guild(guild_id, config)


def _save_state(guild_id: int, state: dict):
    config = db.get_guild(guild_id)
    config["lockdown_state"] = state
    config["lockdown_active"] = bool(state)
    db.update_guild(guild_id, config)


class Lockdown(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="lockdown", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def lockdown(self, ctx: commands.Context):
        guild = ctx.guild
        config = db.get_guild(guild.id)
        if config.get("lockdown_active"):
            return await ctx.send(embed=discord.Embed(
                description="El servidor ya está en lockdown. Usa `,unlock` para revertir.",
                color=0x2b2d31,
            ))

        exempt_ids = set(_get_exempt(guild.id))
        default_role = guild.default_role
        state = {}

        msg = await ctx.send(embed=discord.Embed(
            description="Bloqueando servidor...",
            color=0x2b2d31,
        ))

        for channel in guild.channels:
            if isinstance(channel, discord.CategoryChannel):
                continue
            if channel.id in exempt_ids:
                continue

            overwrite = channel.overwrites_for(default_role)

            if isinstance(channel, discord.TextChannel):
                state[str(channel.id)] = {
                    "view_channel": overwrite.view_channel,
                    "send_messages": overwrite.send_messages,
                }
                overwrite.view_channel = False
                overwrite.send_messages = False
            elif isinstance(channel, discord.VoiceChannel):
                state[str(channel.id)] = {
                    "view_channel": overwrite.view_channel,
                    "connect": overwrite.connect,
                }
                overwrite.view_channel = False
                overwrite.connect = False
            else:
                # Otros tipos de canal (foro, stage, etc.) — solo se oculta.
                state[str(channel.id)] = {
                    "view_channel": overwrite.view_channel,
                }
                overwrite.view_channel = False

            try:
                await channel.set_permissions(default_role, overwrite=overwrite, reason=f"Lockdown por {ctx.author}")
            except discord.Forbidden:
                continue

        _save_state(guild.id, state)

        await msg.edit(embed=discord.Embed(
            description=f"Servidor bloqueado. `{len(state)}` canales ocultos/cerrados, `{len(exempt_ids)}` exentos.",
            color=0xed4245,
        ))

    @commands.command(name="unlock")
    @commands.has_permissions(manage_guild=True)
    async def unlock(self, ctx: commands.Context):
        guild = ctx.guild
        config = db.get_guild(guild.id)
        state = config.get("lockdown_state", {})

        if not state:
            return await ctx.send(embed=discord.Embed(
                description="El servidor no está en lockdown.",
                color=0x2b2d31,
            ))

        default_role = guild.default_role
        msg = await ctx.send(embed=discord.Embed(
            description="Restaurando canales...",
            color=0x2b2d31,
        ))

        restored = 0
        for channel_id, prev in state.items():
            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue

            overwrite = channel.overwrites_for(default_role)
            for key, value in prev.items():
                setattr(overwrite, key, value)

            try:
                if overwrite.is_empty():
                    await channel.set_permissions(default_role, overwrite=None, reason=f"Unlock por {ctx.author}")
                else:
                    await channel.set_permissions(default_role, overwrite=overwrite, reason=f"Unlock por {ctx.author}")
                restored += 1
            except discord.Forbidden:
                continue

        _save_state(guild.id, {})

        await msg.edit(embed=discord.Embed(
            description=f"Servidor restaurado. `{restored}` canales recuperados.",
            color=0x57f287,
        ))

    @lockdown.group(name="exempt", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def lockdown_exempt(self, ctx: commands.Context):
        await ctx.send(embed=discord.Embed(
            description="Usa `,lockdown exempt add <#canal>`, `,lockdown exempt remove <#canal>` o `,lockdown exempt list`.",
            color=0x2b2d31,
        ))

    @lockdown_exempt.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def lockdown_exempt_add(self, ctx: commands.Context, channel: Union[discord.TextChannel, discord.VoiceChannel]):
        ids = _get_exempt(ctx.guild.id)
        if channel.id in ids:
            return await ctx.send(embed=discord.Embed(
                description=f"{channel.mention} ya está exento.",
                color=0x2b2d31,
            ))
        ids.append(channel.id)
        _save_exempt(ctx.guild.id, ids)
        await ctx.send(embed=discord.Embed(
            description=f"{channel.mention} agregado a la lista de exentos.",
            color=0x57f287,
        ))

    @lockdown_exempt.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def lockdown_exempt_remove(self, ctx: commands.Context, channel: Union[discord.TextChannel, discord.VoiceChannel]):
        ids = _get_exempt(ctx.guild.id)
        if channel.id not in ids:
            return await ctx.send(embed=discord.Embed(
                description=f"{channel.mention} no está en la lista de exentos.",
                color=0x2b2d31,
            ))
        ids.remove(channel.id)
        _save_exempt(ctx.guild.id, ids)
        await ctx.send(embed=discord.Embed(
            description=f"{channel.mention} quitado de la lista de exentos.",
            color=0xed4245,
        ))

    @lockdown_exempt.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def lockdown_exempt_list(self, ctx: commands.Context):
        ids = _get_exempt(ctx.guild.id)
        if not ids:
            return await ctx.send(embed=discord.Embed(
                description="No hay canales exentos.",
                color=0x2b2d31,
            ))
        lines = []
        for cid in ids:
            ch = ctx.guild.get_channel(cid)
            lines.append(ch.mention if ch else f"`{cid}`")
        await ctx.send(embed=discord.Embed(
            title="Canales exentos del lockdown",
            description="\n".join(lines),
            color=0x2b2d31,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Lockdown(bot))
