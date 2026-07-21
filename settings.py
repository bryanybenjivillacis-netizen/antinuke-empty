"""
settings.py — Full configuration interface for the AntiNuke bot.

Commands:
  ,antinuke enable/disable
  ,antinuke status
  ,antinuke preset                      — aplica una configuración profesional recomendada
  ,antinuke punishment <ban|kick|strip|mute>
  ,antinuke threshold <module> <number>
  ,antinuke window <module> <seconds>
  ,antinuke module <module> <on|off>
  ,antinuke accountage <days>
  ,antinuke guildage <days>
  ,antinuke admins                      — lista los antinuke admins (ID, mención, rol)
  ,antinuke admins add <@user>          — máximo 3, aparte del dueño y el owner del bot
  ,antinuke admins remove <@user>
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


def _invalidate_cache(guild_id: int):
    """Invalida la caché del motor de antinuke para que los cambios apliquen al instante."""
    try:
        from antinuke import invalidate_config_cache
        invalidate_config_cache(guild_id)
    except ImportError:
        pass


log = logging.getLogger("antinuke.settings")

MAX_ANTINUKE_ADMINS = 3

MODULES = {
    "ban": ("anti_ban", "ban_threshold", "ban_window"),
    "kick": ("anti_kick", "kick_threshold", "kick_window"),
    "channeldelete": ("anti_channel_delete", "channel_delete_threshold", "channel_delete_window"),
    "channelcreate": ("anti_channel_create", "channel_create_threshold", "channel_create_window"),
    "roledelete": ("anti_role_delete", "role_delete_threshold", "role_delete_window"),
    "rolecreate": ("anti_role_create", "role_create_threshold", "role_create_window"),
    "roleadd": ("anti_role_add", None, None),
    "webhook": ("anti_webhook", "webhook_create_threshold", "webhook_create_window"),
    "mention": ("anti_mention", "mention_threshold", "mention_window"),
    "emojidelete": ("anti_emoji_delete", "emoji_delete_threshold", "emoji_delete_window"),
    "botadd": ("anti_bot_add", None, None),
    "everyone": ("anti_everyone_mention", None, None),
    "serverupdate": ("anti_server_update", None, None),
    "prune": ("anti_prune", None, None),
}

PUNISHMENT_CHOICES = ("ban", "kick", "strip", "mute")


def is_manager():
    """Dueño del servidor, owner del bot, administrador, o antinuke admin autorizado."""
    async def predicate(ctx):
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        config = db.get_guild(ctx.guild.id)
        if ctx.author.id in config.get("antinuke_admins", []):
            return True
        return False
    return commands.check(predicate)


def is_owner_level():
    """Solo el dueño del servidor o el owner del bot (para dar/quitar antinuke admins)."""
    async def predicate(ctx):
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if await ctx.bot.is_owner(ctx.author):
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
        _invalidate_cache(ctx.guild.id)
        await ctx.send(embed=build_embed(ctx.guild, "La protección AntiNuke ha sido **activada**.", 0x57f287))

    @antinuke.command(name="disable")
    @is_manager()
    async def antinuke_disable(self, ctx):
        """Disable AntiNuke protection."""
        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["enabled"] = False
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)
        await ctx.send(embed=build_embed(ctx.guild, "La protección AntiNuke ha sido **desactivada**.", 0xed4245))

    @antinuke.command(name="preset")
    @is_manager()
    async def antinuke_preset(self, ctx):
        """
        Aplica una configuración profesional recomendada en un solo comando:
        activa el antinuke, todos los módulos, castigo ban, y thresholds ajustados
        para servidores reales (ni muy sensible, ni muy laxo).
        """
        config = db.get_guild(ctx.guild.id)
        an = config["antinuke"]

        an["enabled"] = True
        an["punishment"] = "ban"

        # Todos los módulos activados
        for module_key in (
            "anti_ban", "anti_kick", "anti_channel_delete", "anti_channel_create",
            "anti_role_delete", "anti_role_create", "anti_role_add", "anti_webhook",
            "anti_mention", "anti_emoji_delete", "anti_bot_add", "anti_everyone_mention",
            "anti_server_update", "anti_prune",
        ):
            an[module_key] = True

        # Thresholds recomendados
        an["ban_threshold"] = 3
        an["ban_window"] = 10
        an["kick_threshold"] = 3
        an["kick_window"] = 10
        an["channel_delete_threshold"] = 2
        an["channel_delete_window"] = 15
        an["channel_create_threshold"] = 3
        an["channel_create_window"] = 15
        an["role_delete_threshold"] = 2
        an["role_delete_window"] = 15
        an["role_create_threshold"] = 3
        an["role_create_window"] = 15
        an["webhook_create_threshold"] = 2
        an["webhook_create_window"] = 15
        an["mention_threshold"] = 8
        an["mention_window"] = 8
        an["emoji_delete_threshold"] = 4
        an["emoji_delete_window"] = 10
        an["min_account_age_days"] = 3

        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        await ctx.send(embed=build_embed(
            ctx.guild,
            "**Preset profesional aplicado.**\n"
            "Antinuke activado, todos los módulos encendidos, castigo `ban`, "
            "thresholds ajustados para uso real. Usa `,antinuke status` para ver el detalle "
            "y `,antinuke threshold`/`,antinuke window` si quieres afinar algo.",
            0x57f287,
        ))

    @antinuke.command(name="status")
    @is_manager()
    async def antinuke_status(self, ctx):
        """Display full AntiNuke configuration."""
        config = db.get_guild(ctx.guild.id)
        an = config["antinuke"]

        enabled_str = "**Activado**" if an.get("enabled") else "**Desactivado**"
        punishment = an.get("punishment", "ban").capitalize()
        wl_count = len(config.get("whitelist", []))
        admin_count = len(config.get("antinuke_admins", []))
        log_ch = config.get("log_channel")
        log_str = f"<#{log_ch}>" if log_ch else "`No configurado`"
        min_age = an.get("min_account_age_days", 0)
        guild_age = an.get("min_guild_age_days", 0)

        def toggle(key):
            return "` on `" if an.get(key, True) else "`off`"

        e = discord.Embed(title="Configuración de AntiNuke", color=0x2b2d31)
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)

        e.add_field(name="Estado", value=enabled_str, inline=True)
        e.add_field(name="Castigo", value=f"`{punishment}`", inline=True)
        e.add_field(name="Canal de Logs", value=log_str, inline=True)
        e.add_field(name="Whitelist", value=f"`{wl_count} usuarios`", inline=True)
        e.add_field(name="Antinuke Admins", value=f"`{admin_count}/{MAX_ANTINUKE_ADMINS}`", inline=True)
        e.add_field(name="Edad Mínima de Cuenta", value=f"`{min_age} días`" if min_age else "`desactivado`", inline=True)
        e.add_field(name="Antigüedad Mínima en Server", value=f"`{guild_age} días`" if guild_age else "`desactivado`", inline=True)

        modules_text = (
            f"Anti-Ban {toggle('anti_ban')}  "
            f"Anti-Kick {toggle('anti_kick')}  "
            f"Eliminar Canal {toggle('anti_channel_delete')}  "
            f"Crear Canal {toggle('anti_channel_create')}\n"
            f"Eliminar Rol {toggle('anti_role_delete')}  "
            f"Crear Rol {toggle('anti_role_create')}  "
            f"Otorgar Rol {toggle('anti_role_add')}  "
            f"Webhook {toggle('anti_webhook')}\n"
            f"Menciones {toggle('anti_mention')}  "
            f"Eliminar Emoji {toggle('anti_emoji_delete')}  "
            f"Agregar Bot {toggle('anti_bot_add')}  "
            f"Everyone {toggle('anti_everyone_mention')}\n"
            f"Actualizar Server {toggle('anti_server_update')}  "
            f"Prune {toggle('anti_prune')}"
        )
        e.add_field(name="Módulos", value=modules_text, inline=False)

        thresholds = (
            f"Ban: `{an.get('ban_threshold',3)}/{an.get('ban_window',10)}s`  "
            f"Kick: `{an.get('kick_threshold',3)}/{an.get('kick_window',10)}s`  "
            f"Elim.Canal: `{an.get('channel_delete_threshold',3)}/{an.get('channel_delete_window',10)}s`\n"
            f"Crear.Canal: `{an.get('channel_create_threshold',3)}/{an.get('channel_create_window',10)}s`  "
            f"Elim.Rol: `{an.get('role_delete_threshold',3)}/{an.get('role_delete_window',10)}s`  "
            f"Crear.Rol: `{an.get('role_create_threshold',3)}/{an.get('role_create_window',10)}s`\n"
            f"Webhook: `{an.get('webhook_create_threshold',3)}/{an.get('webhook_create_window',10)}s`  "
            f"Menciones: `{an.get('mention_threshold',10)}/{an.get('mention_window',8)}s`  "
            f"Elim.Emoji: `{an.get('emoji_delete_threshold',5)}/{an.get('emoji_delete_window',10)}s`"
        )
        e.add_field(name="Thresholds (cantidad/ventana)", value=thresholds, inline=False)

        e.set_footer(text="Usa ,antinuke threshold <módulo> <n> para cambiar valores")
        await ctx.send(embed=e)

    @antinuke.command(name="punishment", aliases=["punish", "action"])
    @is_manager()
    async def antinuke_punishment(self, ctx, punishment: str):
        """Set punishment type: ban, kick, strip, mute."""
        punishment = punishment.lower()
        if punishment not in PUNISHMENT_CHOICES:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Castigo inválido. Elige entre: {', '.join(f'`{p}`' for p in PUNISHMENT_CHOICES)}"
            ))

        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["punishment"] = punishment
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        await ctx.send(embed=build_embed(
            ctx.guild, f"Castigo configurado a `{punishment}`.", 0x57f287
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
                f"Módulo desconocido `{module}`. Disponibles: {', '.join(f'`{m}`' for m in MODULES)}"
            ))

        _, threshold_key, _ = MODULES[module]
        if threshold_key is None:
            return await ctx.send(embed=build_embed(
                ctx.guild, f"El módulo `{module}` no tiene un threshold configurable."
            ))

        if amount < 1:
            return await ctx.send(embed=build_embed(ctx.guild, "El threshold debe ser al menos 1."))

        config = db.get_guild(ctx.guild.id)
        config["antinuke"][threshold_key] = amount
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        await ctx.send(embed=build_embed(
            ctx.guild, f"Threshold de `{module}` configurado a `{amount}`.", 0x57f287
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
                f"Módulo desconocido `{module}`. Disponibles: {', '.join(f'`{m}`' for m in MODULES)}"
            ))

        _, _, window_key = MODULES[module]
        if window_key is None:
            return await ctx.send(embed=build_embed(
                ctx.guild, f"El módulo `{module}` no tiene una ventana configurable."
            ))

        if seconds < 1 or seconds > 3600:
            return await ctx.send(embed=build_embed(ctx.guild, "La ventana debe estar entre 1 y 3600 segundos."))

        config = db.get_guild(ctx.guild.id)
        config["antinuke"][window_key] = seconds
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        await ctx.send(embed=build_embed(
            ctx.guild, f"Ventana de `{module}` configurada a `{seconds}s`.", 0x57f287
        ))

    @antinuke.command(name="module")
    @is_manager()
    async def antinuke_module(self, ctx, module: str, state: str):
        """Toggle a specific module on or off."""
        module = module.lower()
        if module not in MODULES:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Módulo desconocido `{module}`. Disponibles: {', '.join(f'`{m}`' for m in MODULES)}"
            ))

        state = state.lower()
        if state not in ("on", "off", "enable", "disable", "true", "false", "1", "0"):
            return await ctx.send(embed=build_embed(ctx.guild, "El estado debe ser `on` o `off`."))

        enabled = state in ("on", "enable", "true", "1")
        toggle_key, _, _ = MODULES[module]

        config = db.get_guild(ctx.guild.id)
        config["antinuke"][toggle_key] = enabled
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        word = "activado" if enabled else "desactivado"
        color = 0x57f287 if enabled else 0xed4245
        await ctx.send(embed=build_embed(ctx.guild, f"Módulo `{module}` ha sido **{word}**.", color))

    @antinuke.command(name="accountage", aliases=["acctage"])
    @is_manager()
    async def antinuke_accountage(self, ctx, days: int):
        """
        Set minimum account age in days to join.
        Set to 0 to disable.
        """
        if days < 0:
            return await ctx.send(embed=build_embed(ctx.guild, "Los días deben ser 0 o más. Usa 0 para desactivar."))

        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["min_account_age_days"] = days
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        msg = f"Edad mínima de cuenta configurada a `{days} días`." if days else "Verificación de edad de cuenta **desactivada**."
        await ctx.send(embed=build_embed(ctx.guild, msg, 0x57f287))

    @antinuke.command(name="guildage")
    @is_manager()
    async def antinuke_guildage(self, ctx, days: int):
        """
        Set minimum days a member must have been in the guild before executing sensitive actions.
        Set to 0 to disable.
        """
        if days < 0:
            return await ctx.send(embed=build_embed(ctx.guild, "Los días deben ser 0 o más. Usa 0 para desactivar."))

        config = db.get_guild(ctx.guild.id)
        config["antinuke"]["min_guild_age_days"] = days
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        msg = f"Antigüedad mínima en el server configurada a `{days} días`." if days else "Verificación de antigüedad **desactivada**."
        await ctx.send(embed=build_embed(ctx.guild, msg, 0x57f287))

    @antinuke.command(name="instant")
    @is_manager()
    async def antinuke_instant(self, ctx, state: str):
        """
        Modo instantáneo: baja todos los thresholds a 1 acción / 2 segundos.
        Reacciona ante la PRIMERA acción sospechosa, sin esperar un patrón.
        Más agresivo = más rápido, pero más riesgo de falsos positivos
        (ej: un admin real borrando 1 canal por error también se castiga).
        Usa ,antinuke instant off para volver a los thresholds normales.
        """
        state = state.lower()
        if state not in ("on", "off"):
            return await ctx.send(embed=build_embed(ctx.guild, "Usa `on` o `off`."))

        config = db.get_guild(ctx.guild.id)
        an = config["antinuke"]

        if state == "on":
            for _, threshold_key, window_key in MODULES.values():
                if threshold_key:
                    an[threshold_key] = 1
                if window_key:
                    an[window_key] = 2
            msg = (
                "**Modo instantáneo activado.** Cualquier acción sospechosa (1 sola) "
                "dispara el castigo de inmediato, sin esperar un patrón repetido.\n"
                "⚠️ Mayor riesgo de falsos positivos con admins reales."
            )
            color = 0xed4245
        else:
            defaults = default_guild_config()["antinuke"]
            for _, threshold_key, window_key in MODULES.values():
                if threshold_key:
                    an[threshold_key] = defaults[threshold_key]
                if window_key:
                    an[window_key] = defaults[window_key]
            msg = "Modo instantáneo desactivado. Thresholds regresados a los valores normales."
            color = 0x57f287

        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)
        await ctx.send(embed=build_embed(ctx.guild, msg, color))

    @antinuke.command(name="reset")
    @commands.is_owner()
    async def antinuke_reset(self, ctx):
        """Reset AntiNuke config to defaults. (Bot owner only)"""
        config = db.get_guild(ctx.guild.id)
        config["antinuke"] = default_guild_config()["antinuke"]
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)
        await ctx.send(embed=build_embed(ctx.guild, "Configuración de AntiNuke restablecida a los valores por defecto.", 0xfee75c))

    # ── ,antinuke admins ──────────────────────────────────────────────────────

    @antinuke.group(name="admins", invoke_without_command=True)
    @is_manager()
    async def antinuke_admins(self, ctx):
        """Lista los antinuke admins actuales (ID, mención y rol más alto)."""
        config = db.get_guild(ctx.guild.id)
        admin_ids = config.get("antinuke_admins", [])

        if not admin_ids:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"No hay antinuke admins configurados (`0/{MAX_ANTINUKE_ADMINS}`).\n"
                f"Usa `,antinuke admins add <@usuario>` para agregar uno.",
            ))

        lines = []
        for uid in admin_ids:
            member = ctx.guild.get_member(uid)
            if member:
                top_role = member.top_role.mention if member.top_role != ctx.guild.default_role else "`Sin rol`"
                lines.append(f"**ID:** `{uid}` — {member.mention} — Rol: {top_role}")
            else:
                lines.append(f"**ID:** `{uid}` — *(ya no está en el servidor)*")

        e = discord.Embed(
            title=f"Antinuke Admins ({len(admin_ids)}/{MAX_ANTINUKE_ADMINS})",
            description="\n".join(lines),
            color=0x2b2d31,
        )
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.send(embed=e)

    @antinuke_admins.command(name="add")
    @is_owner_level()
    async def antinuke_admins_add(self, ctx, member: discord.Member):
        """Da acceso de antinuke admin a un usuario (máximo 3, aparte del dueño y el owner del bot)."""
        config = db.get_guild(ctx.guild.id)
        admin_ids = config.get("antinuke_admins", [])

        if member.id == ctx.guild.owner_id:
            return await ctx.send(embed=build_embed(ctx.guild, "El dueño del servidor ya tiene acceso total, no necesita ser agregado."))

        if member.id in admin_ids:
            return await ctx.send(embed=build_embed(ctx.guild, f"{member.mention} ya es antinuke admin."))

        if len(admin_ids) >= MAX_ANTINUKE_ADMINS:
            return await ctx.send(embed=build_embed(
                ctx.guild,
                f"Ya hay `{MAX_ANTINUKE_ADMINS}` antinuke admins (el máximo permitido). "
                f"Usa `,antinuke admins remove <@usuario>` para quitar uno primero.",
            ))

        admin_ids.append(member.id)
        config["antinuke_admins"] = admin_ids
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        await ctx.send(embed=build_embed(
            ctx.guild, f"{member.mention} ahora es antinuke admin (`{len(admin_ids)}/{MAX_ANTINUKE_ADMINS}`).", 0x57f287
        ))

    @antinuke_admins.command(name="remove")
    @is_owner_level()
    async def antinuke_admins_remove(self, ctx, member: discord.Member):
        """Quita el acceso de antinuke admin a un usuario."""
        config = db.get_guild(ctx.guild.id)
        admin_ids = config.get("antinuke_admins", [])

        if member.id not in admin_ids:
            return await ctx.send(embed=build_embed(ctx.guild, f"{member.mention} no es antinuke admin."))

        admin_ids.remove(member.id)
        config["antinuke_admins"] = admin_ids
        db.update_guild(ctx.guild.id, config)
        _invalidate_cache(ctx.guild.id)

        await ctx.send(embed=build_embed(
            ctx.guild, f"{member.mention} ya no es antinuke admin (`{len(admin_ids)}/{MAX_ANTINUKE_ADMINS}`).", 0xed4245
        ))

    # ── ,setlogs ──────────────────────────────────────────────────────────────

    @commands.command(name="setlogs", aliases=["logchannel", "logs"])
    @is_manager()
    async def set_logs(self, ctx, channel: discord.TextChannel = None):
        """Set the log channel for AntiNuke events."""
        config = db.get_guild(ctx.guild.id)
        if channel is None:
            config["log_channel"] = None
            db.update_guild(ctx.guild.id, config)
            return await ctx.send(embed=build_embed(ctx.guild, "Canal de logs eliminado.", 0xed4245))

        config["log_channel"] = channel.id
        db.update_guild(ctx.guild.id, config)
        await ctx.send(embed=build_embed(ctx.guild, f"Canal de logs configurado a {channel.mention}.", 0x57f287))

    # ── ,setprefix ────────────────────────────────────────────────────────────

    @commands.command(name="setprefix", aliases=["prefix"])
    @is_manager()
    async def set_prefix(self, ctx, *, prefix: str):
        """Change the bot prefix for this server."""
        if len(prefix) > 5:
            return await ctx.send(embed=build_embed(ctx.guild, "El prefix debe tener 5 caracteres o menos."))

        config = db.get_guild(ctx.guild.id)
        config["prefix"] = prefix
        db.update_guild(ctx.guild.id, config)

        await ctx.send(embed=build_embed(
            ctx.guild, f"Prefix actualizado a `{prefix}`", 0x57f287
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

        e = discord.Embed(title="Configuración del Log Embed", color=color)
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
        Example: ,logembed color #ff0000 or ,logembed color ff0000
        You can use your server's color or any hex.
        """
        hex_color = hex_color.lstrip("#")
        try:
            color_int = int(hex_color, 16)
        except ValueError:
            return await ctx.send(embed=build_embed(ctx.guild, "Color hex inválido. Ejemplo: `#ff0000`"))

        config = db.get_guild(ctx.guild.id)
        if "log_embed" not in config:
            config["log_embed"] = {}
        config["log_embed"]["color"] = color_int
        db.update_guild(ctx.guild.id, config)

        e = discord.Embed(description=f"Color del log embed configurado a `#{hex_color.upper()}`.", color=color_int)
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
            return await ctx.send(embed=build_embed(ctx.guild, "El texto del footer debe tener 100 caracteres o menos."))

        config = db.get_guild(ctx.guild.id)
        if "log_embed" not in config:
            config["log_embed"] = {}
        config["log_embed"]["footer_text"] = text
        db.update_guild(ctx.guild.id, config)

        await ctx.send(embed=build_embed(ctx.guild, f"Texto del footer actualizado a: `{text}`", 0x57f287))

    @logembed.command(name="thumbnail")
    @is_manager()
    async def logembed_thumbnail(self, ctx, state: str):
        """Toggle server icon thumbnail in log embeds: on or off."""
        state = state.lower()
        if state not in ("on", "off"):
            return await ctx.send(embed=build_embed(ctx.guild, "Usa `on` o `off`."))

        enabled = state == "on"
        config = db.get_guild(ctx.guild.id)
        if "log_embed" not in config:
            config["log_embed"] = {}
        config["log_embed"]["thumbnail"] = enabled
        db.update_guild(ctx.guild.id, config)

        word = "activado" if enabled else "desactivado"
        await ctx.send(embed=build_embed(ctx.guild, f"Thumbnail del log embed **{word}**.", 0x57f287))

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
          ,status clear — removes activity
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

        status_map = {
            "online": discord.Status.online,
            "dnd": discord.Status.dnd,
            "idle": discord.Status.idle,
            "invisible": discord.Status.invisible,
        }
        if activity_type in status_map:
            await self.bot.change_presence(status=status_map[activity_type])
            return await ctx.send(embed=discord.Embed(
                description=f"Status cambiado a `{activity_type}`.",
                color=0x57f287,
            ))

        if activity_type == "clear":
            await self.bot.change_presence(activity=None)
            return await ctx.send(embed=discord.Embed(
                description="Actividad removida.",
                color=0x57f287,
            ))

        if not text:
            return await ctx.send(embed=discord.Embed(
                description=f"Falta el texto. Ejemplo: `,status {activity_type} tu texto aquí`",
                color=0xed4245,
            ))

        activity_type_map = {
            "watching": discord.ActivityType.watching,
            "playing": discord.ActivityType.playing,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
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
