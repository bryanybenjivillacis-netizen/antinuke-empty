"""
welcome.py — Sistema de bienvenida con sintaxis $v{} compatible con Bender.

Comandos:
  ,welcome add #canal {embed}$v{message: ...}$v{author: ...}$v{description: ...}
                       $v{thumbnail: {user.avatar}}$v{button: url && texto && /e && enabled}
  ,welcome list                 — ver entradas activas
  ,welcome remove <n>           — eliminar entrada por número
  ,welcome test                 — previsualizar con tu usuario
  ,welcome off                  — desactivar todos los welcomes de este servidor

Variables disponibles: {user.mention} {user.tag} {user.name} {user.avatar} {user.id}
                        {guild.name} {guild.id} {guild.icon} {guild.count} {guild.vanity}
"""

import discord
from discord.ext import commands
from config import db
import logging

log = logging.getLogger("antinuke.welcome")


# ── Parser de sintaxis $v{key: value} ────────────────────────────────────────

def _extract_vblocks(text: str) -> list[str]:
    """
    Extrae el contenido interior de cada bloque $v{...}, respetando
    llaves anidadas (ej: {user.mention} dentro de $v{message: ...}).
    """
    blocks = []
    i = 0
    while i < len(text):
        start = text.find("$v{", i)
        if start == -1:
            break
        depth = 0
        j = start + 2  # apunta a '{'
        while j < len(text):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
                if depth == 0:
                    blocks.append(text[start + 3:j])
                    i = j + 1
                    break
            j += 1
        else:
            break
    return blocks


def _parse_vargs(text: str) -> dict:
    """
    Extrae todos los bloques $v{key: value} del texto.
    Retorna dict con las claves encontradas.
    Soporta múltiples 'button' → lista.
    """
    result = {"buttons": []}
    for block in _extract_vblocks(text):
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
    """Reemplaza {user.mention}, {user.tag}, {user.name}, {user.avatar}, {user.id}, {guild.name}, {guild.id}, {guild.icon}, {guild.count}, {guild.vanity}."""
    guild = member.guild
    return (
        text
        .replace("{user.mention}", member.mention)
        .replace("{user.tag}", str(member))
        .replace("{user.name}", member.display_name)
        .replace("{user.avatar}", member.display_avatar.url)
        .replace("{user.id}", str(member.id))
        .replace("{guild.name}", guild.name)
        .replace("{guild.id}", str(guild.id))
        .replace("{guild.icon}", guild.icon.url if guild.icon else "")
        .replace("{guild.count}", str(guild.member_count))
        .replace("{guild.vanity}", guild.vanity_url_code or "")
    )


def _build_embed(entry: dict, member: discord.Member) -> tuple[discord.Embed, str, list[discord.ui.Button]]:
    """Construye embed + content + botones a partir de una entrada guardada."""
    # Content (mensaje fuera del embed)
    content = _resolve_vars(entry.get("message", ""), member) if entry.get("message") else None

    # Embed
    embed = discord.Embed(color=0x2b2d31)

    author_raw = entry.get("author", "")
    if author_raw:
        # formato: "texto && url_icono" — el && separa texto de icon_url opcional
        parts = [p.strip() for p in author_raw.split("&&")]
        author_text = _resolve_vars(parts[0], member)
        icon_url = parts[1] if len(parts) > 1 and parts[1].startswith("http") else None
        embed.set_author(name=author_text, icon_url=icon_url)

    desc_raw = entry.get("description", "")
    if desc_raw:
        embed.description = _resolve_vars(desc_raw, member)

    thumb_raw = entry.get("thumbnail", "")
    if thumb_raw:
        resolved = _resolve_vars(thumb_raw, member)
        if resolved.startswith("http"):
            embed.set_thumbnail(url=resolved)

    # Botones
    buttons = []
    for btn in entry.get("buttons", []):
        url = _resolve_vars(btn["url"], member)
        label = _resolve_vars(btn["label"], member)
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

        entry = {
            "channel_id": channel.id,
            "message": parsed.get("message", ""),
            "author": parsed.get("author", ""),
            "description": parsed.get("description", ""),
            "thumbnail": parsed.get("thumbnail", ""),
            "buttons": parsed.get("buttons", []),
        }

        entries = _get_welcomes(ctx.guild.id)
        entries.append(entry)
        _save_welcomes(ctx.guild.id, entries)

        await ctx.send(embed=discord.Embed(
            description=f"Welcome agregado en {channel.mention}. Entrada #{len(entries)}.\nUsa `,welcome test` para previsualizar.",
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
