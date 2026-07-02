"""
invites.py — Sistema de tracking de invitaciones.

Comandos:
  ,setinvite channel #canal     — canal de notificaciones
  ,setinvite threshold <n>      — cada cuántas invitaciones notifica (default 5)
  ,setinvite altdays <1-7>      — días mínimos de cuenta para no ser alt (default 3)
  ,invites [@user]              — ver invitaciones de alguien (o tuyas)
  ,invitetop                    — top 5 inviters
  ,resetinvites                 — reiniciar todas las estadísticas (manage_guild)
"""

import discord
from discord.ext import commands
from config import db
import logging
from datetime import timezone

log = logging.getLogger("antinuke.invites")

# Cache de invitaciones de Discord: guild_id → {code: uses}
_invite_cache: dict[int, dict[str, int]] = {}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_config(guild_id: int) -> dict:
    config = db.get_guild(guild_id)
    return config.get("invites", {
        "channel_id": None,
        "threshold": 5,
        "altdays": 3,
        "reward": "",      # texto de recompensa del milestone
        "counts": {},      # user_id (str) → int
        "milestones": {},  # user_id (str) → último milestone notificado
        "invited_by": {},  # user_id (str) → [lista de user_ids invitados]
    })


def _save_config(guild_id: int, cfg: dict):
    config = db.get_guild(guild_id)
    config["invites"] = cfg
    db.update_guild(guild_id, config)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_alt(member: discord.Member, altdays: int) -> bool:
    age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=timezone.utc)).days
    return age < altdays


def _build_milestone_embed(inviter: discord.Member, count: int, reward: str, invited_ids: list) -> discord.Embed:
    embed = discord.Embed(
        description=f"{inviter.mention} consiguió invitar **{count} personas** al servidor 🎉",
        color=0x2b2d31,
    )
    if reward:
        embed.add_field(name="Recompensa", value=reward, inline=False)
    if invited_ids:
        mentions = " ".join(f"<@{uid}>" for uid in invited_ids[-count:])
        embed.add_field(name="Personas invitadas", value=mentions, inline=False)
    embed.set_thumbnail(url=inviter.display_avatar.url)
    embed.set_footer(text=inviter.guild.name)
    return embed


# ── Cog ──────────────────────────────────────────────────────────────────────

class Invites(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Cache de invitaciones ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                invites = await guild.fetch_invites()
                _invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        try:
            invites = await guild.fetch_invites()
            _invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

    # ── Member join ───────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        cfg = _get_config(guild.id)

        # Detectar qué invitación fue usada comparando el cache
        try:
            new_invites = await guild.fetch_invites()
        except Exception:
            return

        old_cache = _invite_cache.get(guild.id, {})
        inviter = None

        for inv in new_invites:
            old_uses = old_cache.get(inv.code, 0)
            if inv.uses > old_uses:
                inviter = inv.inviter
                break

        # Actualizar cache
        _invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if not inviter or inviter.bot:
            return

        # Detectar alt
        altdays = cfg.get("altdays", 3)
        if _is_alt(member, altdays):
            log.info(f"[{guild.name}] {member} detectado como alt (cuenta < {altdays} días)")
            return

        # Sumar invitación
        uid = str(inviter.id)
        counts = cfg.get("counts", {})
        counts[uid] = counts.get(uid, 0) + 1
        cfg["counts"] = counts
        invited_by = cfg.get("invited_by", {})
        invited_by.setdefault(uid, [])
        if member.id not in invited_by[uid]:
            invited_by[uid].append(member.id)
        cfg["invited_by"] = invited_by
        _save_config(guild.id, cfg)

        # Milestone
        threshold = cfg.get("threshold", 5)
        channel_id = cfg.get("channel_id")
        if not channel_id:
            return

        count = counts[uid]
        milestones = cfg.get("milestones", {})
        last_milestone = milestones.get(uid, 0)
        current_milestone = (count // threshold) * threshold

        if current_milestone > last_milestone and current_milestone > 0:
            milestones[uid] = current_milestone
            cfg["milestones"] = milestones
            _save_config(guild.id, cfg)

            channel = guild.get_channel(int(channel_id))
            inviter_member = guild.get_member(inviter.id)
            if channel and inviter_member:
                try:
                    reward = cfg.get("reward", "")
                    invited_ids = cfg.get("invited_by", {}).get(uid, [])
                    await channel.send(embed=_build_milestone_embed(inviter_member, current_milestone, reward, invited_ids))
                except discord.Forbidden:
                    pass

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        cache = _invite_cache.setdefault(invite.guild.id, {})
        cache[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        cache = _invite_cache.get(invite.guild.id, {})
        cache.pop(invite.code, None)

    # ── Comandos ──────────────────────────────────────────────────────────────

    @commands.group(name="setinvite", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def setinvite(self, ctx: commands.Context):
        await ctx.send(embed=discord.Embed(
            description="Usa `,setinvite channel #canal`, `,setinvite threshold <n>` o `,setinvite altdays <1-7>`.",
            color=0x2b2d31,
        ))

    @setinvite.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def setinvite_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        cfg = _get_config(ctx.guild.id)
        cfg["channel_id"] = channel.id
        _save_config(ctx.guild.id, cfg)
        await ctx.send(embed=discord.Embed(
            description=f"Canal configurado: {channel.mention}",
            color=0x57f287,
        ))

    @setinvite.command(name="threshold")
    @commands.has_permissions(manage_guild=True)
    async def setinvite_threshold(self, ctx: commands.Context, n: int, *, reward: str = ""):
        """Ejemplo: ,setinvite threshold 10 tiene 10% más de ganar en giveaways"""
        if n < 1:
            return await ctx.send(embed=discord.Embed(
                description="El umbral debe ser al menos `1`.",
                color=0xed4245,
            ))
        cfg = _get_config(ctx.guild.id)
        cfg["threshold"] = n
        cfg["reward"] = reward.strip()
        _save_config(ctx.guild.id, cfg)
        desc = f"Notificación cada `{n}` invitaciones."
        if reward:
            desc += "\nRecompensa: " + reward.strip()
        await ctx.send(embed=discord.Embed(description=desc, color=0x57f287))

    @setinvite.command(name="altdays")
    @commands.has_permissions(manage_guild=True)
    async def setinvite_altdays(self, ctx: commands.Context, days: int):
        if days < 1 or days > 7:
            return await ctx.send(embed=discord.Embed(
                description="El valor debe estar entre `1` y `7`.",
                color=0xed4245,
            ))
        cfg = _get_config(ctx.guild.id)
        cfg["altdays"] = days
        _save_config(ctx.guild.id, cfg)
        await ctx.send(embed=discord.Embed(
            description=f"Cuentas menores a `{days}` días serán ignoradas como alts.",
            color=0x57f287,
        ))

    @commands.command(name="invites")
    async def invites_cmd(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        cfg = _get_config(ctx.guild.id)
        count = cfg.get("counts", {}).get(str(member.id), 0)
        await ctx.send(embed=discord.Embed(
            description=f"{member.mention} tiene **{count}** invitaciones.",
            color=0x2b2d31,
        ))

    @commands.command(name="invitetop")
    async def invitetop(self, ctx: commands.Context):
        cfg = _get_config(ctx.guild.id)
        counts = cfg.get("counts", {})
        if not counts:
            return await ctx.send(embed=discord.Embed(
                description="No hay datos de invitaciones aún.",
                color=0x2b2d31,
            ))

        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
        lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, (uid, count) in enumerate(sorted_counts):
            member = ctx.guild.get_member(int(uid))
            name = member.mention if member else f"`{uid}`"
            lines.append(f"{medals[i]} {name} — **{count}** invitaciones")

        await ctx.send(embed=discord.Embed(
            title="Top 5 Inviters",
            description="\n".join(lines),
            color=0x2b2d31,
        ))

    @commands.command(name="resetinvites")
    @commands.has_permissions(manage_guild=True)
    async def resetinvites(self, ctx: commands.Context):
        cfg = _get_config(ctx.guild.id)
        cfg["counts"] = {}
        cfg["milestones"] = {}
        _save_config(ctx.guild.id, cfg)
        await ctx.send(embed=discord.Embed(
            description="Estadísticas de invitaciones reiniciadas.",
            color=0xed4245,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
