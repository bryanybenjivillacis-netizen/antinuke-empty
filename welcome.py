"""
welcome.py — Sistema de bienvenida con sintaxis $v{} compatible con Bender.

Comandos:
  ,welcome add #canal {embed}$v{message: ...}$v{author: ...}$v{description: ...}
           $v{thumbnail: {user.avatar}}$v{button: url && texto && /e && enabled}
  ,welcome list          — ver entradas activas
  ,welcome remove <n>    — eliminar entrada por número
  ,welcome test          — previsualizar con tu usuario
  ,welcome off           — desactivar todos los welcomes de este servidor

Variables disponibles: {user.mention} {user.tag} {user.avatar} {guild.count}
"""

import discord
from discord.ext import commands
from config import db
import logging
import re

log = logging.getLogger("antinuke.welcome")


# ── Parser de sintaxis $v{key: value} ────────────────────────────────────────

def _parse_vargs(text: str) -> dict:
    """
    Extrae todos los bloques $v{key: value} del texto.
    Retorna dict con las claves encontradas.
    Soporta múltiples 'button' → lista.
    """
    result = {"buttons": []}
    # Encuentra todos los bloques $v{...}
    pattern = re.compile(r'\$v\{([^}]+)\}', re.DOTALL)
    for match in pattern.finditer(text):
        block = match.group(1)
        # Separar key: value en el primer ':'
        if ':' not in block:
            continue
        key, _, value = block.partition(':')
        key = key.strip().lower()
        value = value.strip()

        if key == "button":
            # formato: url && texto && /emoji && enabled
            parts = [p.strip() for p in value.split("&&")]
            # parts[0]=url, parts[1]=texto, parts[2]=emoji_o_path, parts[3]=enabled
            url = parts[0] if len(parts) > 0 else ""
            label = parts[1] if len(parts) > 1 else "Click"
            enabled = "enabled" in value.lower()
            if enabled and url:
                result["buttons"].append({"url": url, "label": label})
            elif enabled and not url:
                # botón sin url (guild.count style) — lo ignoramos, no soportado por discord.py sin url
                pass
        else:
            result[key] = value

    return result


def _resolve_vars(text: str, member: discord.Member) -> str:
    """Reemplaza {user.mention}, {user.tag}, {user.avatar}, {guild.count}."""
    return (
        text
        .replace("{user.mention}", member.mention)
        .replace("{user.tag}", str(member))
        .replace("{user.avatar}", member.display_avatar.url)
        .replace("{guild.count}", str(member.guild.member_count))
    )


def _resolve_vars_in_dict(entry: dict, member: discord.Member) -> dict:
    """Resuelve todas las variables en un diccionario de entrada."""
    resolved = entry.copy()
    for key in ["message", "author", "description", "thumbnail"]:
        if key in resolved and resolved[key]:
            resolved[key] = _resolve_vars(resolved[key], member)
    if "buttons" in resolved:
        resolved["buttons"] = [
            {
                "url": _resolve_vars(btn["url"], member),
                "label": _resolve_vars(btn["label"], member)
            }
            for btn in resolved["buttons"]
        ]
    return resolved


def _build_embed(entry: dict, member: discord.Member) -> tuple[discord.Embed, str, list[discord.ui.Button]]:
    """Construye embed + content + botones a partir de una entrada guardada."""
    # Resolvemos TODAS las variables primero
    resolved_entry = _resolve_vars_in_dict(entry, member)
    
    # Content (mensaje fuera del embed)
    content = resolved_entry.get("message", None)
    
    # Embed
    embed = discord.Embed(color=0x2b2d31)
    
    author_raw = resolved_entry.get("author", "")
    if author_raw:
        parts = [p.strip() for p in author_raw.split("&&")]
        author_text = parts[0]
        icon_url = parts[1] if len(parts) > 1 and parts[1].startswith("http") else None
        embed.set_author(name=author_text, icon_url=icon_url)
    
    desc_raw = resolved_entry.get("description", "")
    if desc_raw:
        embed.description = desc_raw
    
    thumb_raw = resolved_entry.get("thumbnail", "")
    if thumb_raw and thumb_raw.startswith("http"):
        embed.set_thumbnail(url=thumb_raw)
    
    # Botones
    buttons = []
    for btn in resolved_entry.get("buttons", []):
        url = btn["url"]
        label = btn["label"]
        if url.startswith("http"):
            buttons.append(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    
    return embed, content, buttons


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_welcomes(guild_id: int) -> list:
    config = db.get_guild(guild_id)
    return config.get("welcome_entries", [])


def _save_welcomes(guild_id: int, entries: list):
    config = db.get_guild(guild_id)
    config["welcome_entries"] = entries
    db.update_guild(guild_id, config)


# ── Cog ──────────────────────────────────────────────────────────────────────

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        entries = _get_welcomes(member.guild.id)
        for entry in entries:
            channel = member.guild.get_channel(int(entry["channel_id"]))
            if not channel:
                continue
            embed, content, buttons = _build_embed(entry, member)
            try:
                if buttons:
                    view = discord.ui.View()
                    for btn in buttons:
                        view.add_item(btn)
                    await channel.send(content=content, embed=embed, view=view)
                else:
                    await channel.send(content=content, embed=embed)
            except discord.Forbidden:
                log.warning(f"[{member.guild.name}] Sin permisos para mandar welcome en {channel.name}")
            except Exception as e:
                log.error(f"[{member.guild.name}] Welcome error: {e}")

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx: commands.Context):
        await ctx.send(embed=discord.Embed(
            description="Usa `,welcome add`, `,welcome list`, `,welcome remove <n>`, `,welcome test`, `,welcome off`.",
            color=0x2b2d31,
        ))

    @welcome.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def welcome_add(self, ctx: commands.Context, channel: discord.TextChannel, *, config_text: str):
        """
        Agrega un mensaje de bienvenida.
        Ejemplo:
          ,welcome add #chat {embed}$v{message: {user.mention}}$v{author: welcome, {user.tag}!}$v{description: hola}$v{thumbnail: {user.avatar}}
        """
        parsed = _parse_vargs(config_text)

        # Guardamos el texto ORIGINAL con las variables sin resolver
        # para que se resuelvan cuando un nuevo miembro entre
        entry = {
            "channel_id": channel.id,
            "message":     parsed.get("message", ""),
            "author":      parsed.get("author", ""),
            "description": parsed.get("description", ""),
            "thumbnail":   parsed.get("thumbnail", ""),
            "buttons":     parsed.get("buttons", []),
        }

        entries = _get_welcomes(ctx.guild.id)
        entries.append(entry)
        _save_welcomes(ctx.guild.id, entries)

        # Mostramos una previsualización al usuario que configuró
        embed, content, buttons = _build_embed(entry, ctx.author)
        preview_msg = "**✅ Welcome agregado! Previsualización:**\n"
        if buttons:
            view = discord.ui.View()
            for btn in buttons:
                view.add_item(btn)
            await ctx.send(content=preview_msg, embed=embed, view=view)
        else:
            await ctx.send(content=preview_msg, embed=embed)

        await ctx.send(embed=discord.Embed(
            description=f"Welcome guardado en {channel.mention}. Entrada #{len(entries)}.",
            color=0x57f287,
        ))

    @welcome.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def welcome_list(self, ctx: commands.Context):
        entries = _get_welcomes(ctx.guild.id)
        if not entries:
            return await ctx.send(embed=discord.Embed(
                description="No hay welcomes configurados.",
                color=0x2b2d31,
            ))
        lines = []
        for i, e in enumerate(entries, 1):
            ch = ctx.guild.get_channel(int(e["channel_id"]))
            ch_mention = ch.mention if ch else f"`{e['channel_id']}`"
            lines.append(f"**{i}.** {ch_mention}")
        await ctx.send(embed=discord.Embed(
            title="Welcome entries",
            description="\n".join(lines),
            color=0x2b2d31,
        ))

    @welcome.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def welcome_remove(self, ctx: commands.Context, n: int):
        entries = _get_welcomes(ctx.guild.id)
        if n < 1 or n > len(entries):
            return await ctx.send(embed=discord.Embed(
                description=f"Número inválido. Hay `{len(entries)}` entradas.",
                color=0xed4245,
            ))
        removed = entries.pop(n - 1)
        _save_welcomes(ctx.guild.id, entries)
        ch = ctx.guild.get_channel(int(removed["channel_id"]))
        await ctx.send(embed=discord.Embed(
            description=f"Entrada #{n} eliminada ({ch.mention if ch else 'canal desconocido'}).",
            color=0xed4245,
        ))

    @welcome.command(name="test")
    @commands.has_permissions(manage_guild=True)
    async def welcome_test(self, ctx: commands.Context):
        entries = _get_welcomes(ctx.guild.id)
        if not entries:
            return await ctx.send(embed=discord.Embed(
                description="No hay welcomes configurados. Usa `,welcome add` primero.",
                color=0x2b2d31,
            ))
        # Previsualiza la primera entrada en el canal actual
        entry = entries[0]
        embed, content, buttons = _build_embed(entry, ctx.author)
        if buttons:
            view = discord.ui.View()
            for btn in buttons:
                view.add_item(btn)
            await ctx.send(content=content, embed=embed, view=view)
        else:
            await ctx.send(content=content, embed=embed)

    @welcome.command(name="off")
    @commands.has_permissions(manage_guild=True)
    async def welcome_off(self, ctx: commands.Context):
        _save_welcomes(ctx.guild.id, [])
        await ctx.send(embed=discord.Embed(
            description="Todos los welcomes desactivados.",
            color=0xed4245,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
