"""
giveaway.py — Sistema de giveaways con bonus de probabilidad.

Comandos:
  ,gcreate #canal <segundos> <premio>   — crear giveaway
  ,gend <message_id>                    — terminar giveaway antes de tiempo
  ,greroll <message_id>                 — rerollear ganador
  ,gbonus @user <3-50>                  — dar bonus % a un usuario
  ,gbonus remove @user                  — quitar bonus
  ,gbonus list                          — ver todos los bonus activos
"""

import discord
from discord.ext import commands
from config import db
import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta

log = logging.getLogger("antinuke.giveaway")

GIVEAWAY_EMOJI = "🎉"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_giveaways(guild_id: int) -> dict:
    config = db.get_guild(guild_id)
    return config.get("giveaways", {})  # message_id (str) → giveaway data


def _save_giveaways(guild_id: int, data: dict):
    config = db.get_guild(guild_id)
    config["giveaways"] = data
    db.update_guild(guild_id, config)


def _get_bonuses(guild_id: int) -> dict:
    config = db.get_guild(guild_id)
    return config.get("giveaway_bonuses", {})  # user_id (str) → int (%)


def _save_bonuses(guild_id: int, data: dict):
    config = db.get_guild(guild_id)
    config["giveaway_bonuses"] = data
    db.update_guild(guild_id, config)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pick_winner(participants: list[int], bonuses: dict) -> int | None:
    """
    Elige ganador con peso según bonus.
    Base: 100 tickets. Bonus 10% → 110 tickets.
    """
    if not participants:
        return None
    pool = []
    for uid in participants:
        bonus = bonuses.get(str(uid), 0)
        tickets = 100 + bonus
        pool.extend([uid] * tickets)
    return random.choice(pool)


def _build_giveaway_embed(prize: str, end_time: datetime, ended: bool = False, winner_id: int = None, participants: int = 0) -> discord.Embed:
    embed = discord.Embed(color=0x2b2d31)
    embed.title = f"🎉 {prize}"
    if ended:
        embed.description = f"**Ganador:** <@{winner_id}>" if winner_id else "No hubo participantes."
        embed.set_footer(text="Giveaway terminado")
    else:
        ts = int(end_time.timestamp())
        embed.description = f"Termina: <t:{ts}:R>"
        embed.add_field(name="Participantes", value=str(participants), inline=True)
        embed.set_footer(text=f"Termina el {end_time.strftime('%d/%m/%Y %H:%M')} UTC")
    return embed


def _parse_duration(text: str) -> int | None:
    """Convierte '1m', '2h', '3d' a segundos. Retorna None si inválido."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    text = text.strip().lower()
    if text[-1] in units and text[:-1].isdigit():
        return int(text[:-1]) * units[text[-1]]
    if text.isdigit():
        return int(text)
    return None


class JoinGiveawayView(discord.ui.View):
    def __init__(self, cog, guild_id: int, message_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.message_id = message_id

    @discord.ui.button(label="🎉 Participar", style=discord.ButtonStyle.primary, custom_id="giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaways = _get_giveaways(self.guild_id)
        data = giveaways.get(str(self.message_id))
        if not data or data.get("ended"):
            return await interaction.response.send_message("Este giveaway ya terminó.", ephemeral=True)
        uid = interaction.user.id
        participants = data.get("participants", [])
        if uid in participants:
            participants.remove(uid)
            msg = "Saliste del giveaway."
        else:
            participants.append(uid)
            msg = "¡Te uniste al giveaway! 🎉"
        data["participants"] = participants
        giveaways[str(self.message_id)] = data
        _save_giveaways(self.guild_id, giveaways)

        # Actualizar embed con nuevo conteo
        end_time = datetime.fromisoformat(data["end_time"])
        embed = _build_giveaway_embed(data["prize"], end_time, participants=len(participants))
        await interaction.response.edit_message(embed=embed)
        await interaction.followup.send(msg, ephemeral=True)




class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks: dict[str, asyncio.Task] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            giveaways = _get_giveaways(guild.id)
            for msg_id, data in giveaways.items():
                if not data.get("ended"):
                    end_time = datetime.fromisoformat(data["end_time"])
                    remaining = (end_time - datetime.now(timezone.utc)).total_seconds()
                    if remaining > 0:
                        task = asyncio.create_task(self._wait_and_end(guild.id, int(msg_id), remaining))
                        self._tasks[msg_id] = task
                    else:
                        await self._end_giveaway(guild.id, int(msg_id))

    async def _wait_and_end(self, guild_id: int, message_id: int, delay: float):
        await asyncio.sleep(delay)
        await self._end_giveaway(guild_id, message_id)

    async def _end_giveaway(self, guild_id: int, message_id: int):
        giveaways = _get_giveaways(guild_id)
        data = giveaways.get(str(message_id))
        if not data or data.get("ended"):
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(int(data["channel_id"]))
        if not channel:
            return

        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            return

        # Participantes guardados en DB (via botón)
        participants = data.get("participants", [])

        bonuses = _get_bonuses(guild_id)
        winner_id = _pick_winner(participants, bonuses)

        end_time = datetime.fromisoformat(data["end_time"])
        embed = _build_giveaway_embed(data["prize"], end_time, ended=True, winner_id=winner_id)
        await message.edit(embed=embed, view=None)

        if winner_id:
            await channel.send(f"🎉 ¡Felicidades <@{winner_id}>! Ganaste **{data['prize']}**.")
        else:
            await channel.send("No hubo participantes suficientes para el giveaway.")

        # Marcar como terminado
        data["ended"] = True
        data["winner_id"] = winner_id
        data["participants"] = participants
        giveaways[str(message_id)] = data
        _save_giveaways(guild_id, giveaways)

    # ── Comandos ──────────────────────────────────────────────────────────────

    @commands.command(name="gcreate")
    @commands.has_permissions(manage_guild=True)
    async def gcreate(self, ctx: commands.Context, channel: discord.TextChannel, duration: str, *, prize: str):
        """Ejemplo: ,gcreate #giveaways 1h Nitro | ,gcreate #giveaways 30m Rol VIP"""
        seconds = _parse_duration(duration)
        if not seconds or seconds < 10:
            return await ctx.send(embed=discord.Embed(
                description="Duración inválida. Usa `1m`, `2h`, `1d`, etc. Mínimo 10 segundos.",
                color=0xed4245,
            ))

        end_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        embed = _build_giveaway_embed(prize, end_time, participants=0)

        data = {
            "channel_id": channel.id,
            "prize": prize,
            "end_time": end_time.isoformat(),
            "ended": False,
            "winner_id": None,
            "participants": [],
        }
        # Mandar mensaje primero para obtener el ID
        msg = await channel.send(embed=embed)

        view = JoinGiveawayView(self, ctx.guild.id, msg.id)
        await msg.edit(view=view)

        giveaways = _get_giveaways(ctx.guild.id)
        giveaways[str(msg.id)] = data
        _save_giveaways(ctx.guild.id, giveaways)

        task = asyncio.create_task(self._wait_and_end(ctx.guild.id, msg.id, seconds))
        self._tasks[str(msg.id)] = task

        if channel != ctx.channel:
            await ctx.send(embed=discord.Embed(
                description=f"Giveaway creado en {channel.mention}.",
                color=0x57f287,
            ))

    @commands.command(name="gend")
    @commands.has_permissions(manage_guild=True)
    async def gend(self, ctx: commands.Context, message_id: int):
        giveaways = _get_giveaways(ctx.guild.id)
        if str(message_id) not in giveaways:
            return await ctx.send(embed=discord.Embed(
                description="No encontré ese giveaway.",
                color=0xed4245,
            ))
        task = self._tasks.pop(str(message_id), None)
        if task:
            task.cancel()
        await self._end_giveaway(ctx.guild.id, message_id)

    @commands.command(name="greroll")
    @commands.has_permissions(manage_guild=True)
    async def greroll(self, ctx: commands.Context, message_id: int):
        giveaways = _get_giveaways(ctx.guild.id)
        data = giveaways.get(str(message_id))
        if not data or not data.get("ended"):
            return await ctx.send(embed=discord.Embed(
                description="Giveaway no encontrado o no ha terminado.",
                color=0xed4245,
            ))

        participants = data.get("participants", [])
        bonuses = _get_bonuses(ctx.guild.id)
        winner_id = _pick_winner(participants, bonuses)

        if winner_id:
            await ctx.send(f"🎉 Nuevo ganador: <@{winner_id}>! Felicidades por **{data['prize']}**.")
        else:
            await ctx.send(embed=discord.Embed(
                description="No hay participantes para rerollear.",
                color=0xed4245,
            ))

    # ── Bonus ─────────────────────────────────────────────────────────────────

    @commands.group(name="gbonus", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def gbonus(self, ctx: commands.Context, member: discord.Member, percent: int):
        """Ejemplo: ,gbonus @user 20"""
        if percent < 3 or percent > 50:
            return await ctx.send(embed=discord.Embed(
                description="El bonus debe estar entre `3%` y `50%`.",
                color=0xed4245,
            ))
        bonuses = _get_bonuses(ctx.guild.id)
        bonuses[str(member.id)] = percent
        _save_bonuses(ctx.guild.id, bonuses)
        await ctx.send(embed=discord.Embed(
            description=f"{member.mention} tiene ahora **+{percent}%** de probabilidad en giveaways.",
            color=0x57f287,
        ))

    @gbonus.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def gbonus_remove(self, ctx: commands.Context, member: discord.Member):
        bonuses = _get_bonuses(ctx.guild.id)
        if str(member.id) not in bonuses:
            return await ctx.send(embed=discord.Embed(
                description=f"{member.mention} no tiene bonus.",
                color=0xed4245,
            ))
        del bonuses[str(member.id)]
        _save_bonuses(ctx.guild.id, bonuses)
        await ctx.send(embed=discord.Embed(
            description=f"Bonus eliminado para {member.mention}.",
            color=0xed4245,
        ))

    @gbonus.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def gbonus_list(self, ctx: commands.Context):
        bonuses = _get_bonuses(ctx.guild.id)
        if not bonuses:
            return await ctx.send(embed=discord.Embed(
                description="No hay bonus activos.",
                color=0x2b2d31,
            ))
        lines = []
        for uid, percent in bonuses.items():
            member = ctx.guild.get_member(int(uid))
            name = member.mention if member else f"`{uid}`"
            lines.append(f"{name} — **+{percent}%**")
        await ctx.send(embed=discord.Embed(
            title="Bonus activos",
            description="\n".join(lines),
            color=0x2b2d31,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
