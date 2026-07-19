"""
voice.py — Sistema de voice channels temporales (Join to Create) con panel de control.

Setup:
  ,voiceset setup <categoria>   — crea el canal "➕ Join to Create" en esa categoría
  ,voiceset hub <#canal_voz>    — usa un canal de voz ya existente como hub
  ,voiceset off                — desactiva el sistema

Automático:
  Al unirse al canal hub, se crea un VC nuevo para el usuario (owner), se le mueve ahí,
  y se manda el panel de control en el chat del canal. Se borra solo cuando queda vacío.

Panel (botones) + comandos de texto equivalentes:
  ,voice lock / ,voice unlock
  ,voice hide / ,voice unhide
  ,voice rename <nombre>
  ,voice limit <numero>
  ,voice kick <@usuario>
  ,voice claim
"""

import discord
from discord.ext import commands
from config import db
import logging

log = logging.getLogger("antinuke.voice")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_config(guild_id: int) -> dict:
    return db.get_guild(guild_id)


def _save_config(guild_id: int, config: dict):
    db.update_guild(guild_id, config)


def _get_temp_channels(guild_id: int) -> dict:
    config = _get_config(guild_id)
    return config.get("voice_temp_channels", {})


def _save_temp_channels(guild_id: int, temp: dict):
    config = _get_config(guild_id)
    config["voice_temp_channels"] = temp
    _save_config(guild_id, config)


def _get_owner(guild_id: int, channel_id: int):
    temp = _get_temp_channels(guild_id)
    owner = temp.get(str(channel_id))
    return int(owner) if owner else None


def _is_owner_or_admin(member: discord.Member, guild_id: int, channel_id: int) -> bool:
    owner = _get_owner(guild_id, channel_id)
    return member.guild_permissions.manage_channels or (owner is not None and member.id == owner)


# ── Panel de botones ──────────────────────────────────────────────────────────

class VoicePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _check(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message("Esto solo funciona dentro del VC.", ephemeral=True)
            return None
        if not _is_owner_or_admin(interaction.user, interaction.guild.id, channel.id):
            await interaction.response.send_message("Solo el dueño del canal puede usar esto.", ephemeral=True)
            return None
        return channel

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="vc_lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message("Canal bloqueado 🔒", ephemeral=True)

    @discord.ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary, custom_id="vc_unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        await channel.set_permissions(interaction.guild.default_role, connect=True)
        await interaction.response.send_message("Canal desbloqueado 🔓", ephemeral=True)

    @discord.ui.button(label="Hide", emoji="🙈", style=discord.ButtonStyle.secondary, custom_id="vc_hide")
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        await channel.set_permissions(interaction.guild.default_role, view_channel=False)
        await interaction.response.send_message("Canal oculto 🙈", ephemeral=True)

    @discord.ui.button(label="Unhide", emoji="👁️", style=discord.ButtonStyle.secondary, custom_id="vc_unhide")
    async def unhide(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        await channel.set_permissions(interaction.guild.default_role, view_channel=True)
        await interaction.response.send_message("Canal visible 👁️", ephemeral=True)

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.primary, custom_id="vc_rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        await interaction.response.send_modal(RenameModal(channel))

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.primary, custom_id="vc_limit")
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        await interaction.response.send_modal(LimitModal(channel))

    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger, custom_id="vc_kick")
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._check(interaction)
        if not channel:
            return
        view = KickSelectView(channel)
        await interaction.response.send_message("Elige a quién sacar:", view=view, ephemeral=True)

    @discord.ui.button(label="Claim", emoji="👑", style=discord.ButtonStyle.success, custom_id="vc_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.VoiceChannel):
            return await interaction.response.send_message("Esto solo funciona dentro del VC.", ephemeral=True)

        owner_id = _get_owner(interaction.guild.id, channel.id)
        owner_still_here = owner_id and interaction.guild.get_member(owner_id) in channel.members

        if owner_still_here:
            return await interaction.response.send_message("El dueño sigue en el canal, no se puede reclamar.", ephemeral=True)

        temp = _get_temp_channels(interaction.guild.id)
        temp[str(channel.id)] = interaction.user.id
        _save_temp_channels(interaction.guild.id, temp)

        await channel.set_permissions(interaction.user, manage_channels=True, move_members=True, mute_members=True)
        await interaction.response.send_message(f"{interaction.user.mention} ahora es el dueño de este canal 👑")


class RenameModal(discord.ui.Modal, title="Renombrar canal"):
    name = discord.ui.TextInput(label="Nuevo nombre", max_length=100)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        await self.channel.edit(name=str(self.name))
        await interaction.response.send_message(f"Canal renombrado a **{self.name}**.", ephemeral=True)


class LimitModal(discord.ui.Modal, title="Límite de usuarios"):
    limit = discord.ui.TextInput(label="Límite (0 = sin límite)", max_length=3)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.limit))
        except ValueError:
            return await interaction.response.send_message("Eso no es un número válido.", ephemeral=True)
        await self.channel.edit(user_limit=max(0, min(value, 99)))
        await interaction.response.send_message(f"Límite ajustado a `{value}`.", ephemeral=True)


class KickSelectView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(timeout=60)
        self.add_item(KickSelect(channel))


class KickSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(placeholder="Selecciona un usuario para sacar del VC")
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if member.voice and member.voice.channel and member.voice.channel.id == self.channel.id:
            await member.move_to(None, reason=f"Kick del VC por {interaction.user}")
            await interaction.response.send_message(f"{member.mention} fue sacado del canal.", ephemeral=True)
        else:
            await interaction.response.send_message("Ese usuario ya no está en el canal.", ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────────────────

class Voice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(VoicePanel())  # persistente tras reinicios

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        config = _get_config(guild.id)
        hub_id = config.get("voice_hub_channel_id")
        temp = _get_temp_channels(guild.id)

        # Se unió al hub → crear canal nuevo
        if hub_id and after.channel and after.channel.id == int(hub_id):
            category = after.channel.category
            new_channel = await guild.create_voice_channel(
                name=f"{member.display_name}'s VC",
                category=category,
                reason=f"Voice temporal para {member}",
            )
            await new_channel.set_permissions(member, manage_channels=True, move_members=True, mute_members=True)
            await member.move_to(new_channel)

            temp[str(new_channel.id)] = member.id
            _save_temp_channels(guild.id, temp)

            try:
                await new_channel.send(
                    embed=discord.Embed(
                        description=f"🎧 Canal de {member.mention}. Usa los botones para controlarlo.",
                        color=0x2b2d31,
                    ),
                    view=VoicePanel(),
                )
            except discord.Forbidden:
                pass

        # Salió de un canal temporal → borrar si quedó vacío
        if before.channel and str(before.channel.id) in temp:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Voice temporal vacío")
                except discord.NotFound:
                    pass
                temp.pop(str(before.channel.id), None)
                _save_temp_channels(guild.id, temp)

    @commands.group(name="voiceset", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def voiceset(self, ctx: commands.Context):
        await ctx.send(embed=discord.Embed(
            description="Usa `,voiceset setup <categoria>`, `,voiceset hub <#canal_voz>` o `,voiceset off`.",
            color=0x2b2d31,
        ))

    @voiceset.command(name="setup")
    @commands.has_permissions(manage_guild=True)
    async def voiceset_setup(self, ctx: commands.Context, *, category_name: str):
        category = discord.utils.get(ctx.guild.categories, name=category_name)
        if not category:
            category = await ctx.guild.create_category(category_name, reason=f"Voice setup por {ctx.author}")

        hub = await ctx.guild.create_voice_channel(
            "➕ Join to Create",
            category=category,
            reason=f"Voice hub creado por {ctx.author}",
        )

        config = _get_config(ctx.guild.id)
        config["voice_hub_channel_id"] = hub.id
        _save_config(ctx.guild.id, config)

        await ctx.send(embed=discord.Embed(
            description=f"Listo. Únete a {hub.mention} para crear tu propio canal de voz.",
            color=0x57f287,
        ))

    @voiceset.command(name="hub")
    @commands.has_permissions(manage_guild=True)
    async def voiceset_hub(self, ctx: commands.Context, channel: discord.VoiceChannel):
        config = _get_config(ctx.guild.id)
        config["voice_hub_channel_id"] = channel.id
        _save_config(ctx.guild.id, config)
        await ctx.send(embed=discord.Embed(
            description=f"{channel.mention} ahora es el canal para crear VCs.",
            color=0x57f287,
        ))

    @voiceset.command(name="off")
    @commands.has_permissions(manage_guild=True)
    async def voiceset_off(self, ctx: commands.Context):
        config = _get_config(ctx.guild.id)
        config["voice_hub_channel_id"] = None
        _save_config(ctx.guild.id, config)
        await ctx.send(embed=discord.Embed(
            description="Sistema de voice temporal desactivado.",
            color=0xed4245,
        ))

    @commands.group(name="voice", invoke_without_command=True)
    async def voice(self, ctx: commands.Context):
        await ctx.send(embed=discord.Embed(
            description="Usa `,voice lock`, `,voice unlock`, `,voice hide`, `,voice unhide`, `,voice rename <nombre>`, `,voice limit <n>`, `,voice kick <@user>` o `,voice claim` (dentro de tu VC temporal).",
            color=0x2b2d31,
        ))

    async def _current_temp_channel(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(embed=discord.Embed(description="Debes estar en un canal de voz temporal.", color=0xed4245))
            return None
        channel = ctx.author.voice.channel
        if str(channel.id) not in _get_temp_channels(ctx.guild.id):
            await ctx.send(embed=discord.Embed(description="Ese no es un canal de voz temporal.", color=0xed4245))
            return None
        if not _is_owner_or_admin(ctx.author, ctx.guild.id, channel.id):
            await ctx.send(embed=discord.Embed(description="No eres el dueño de este canal.", color=0xed4245))
            return None
        return channel

    @voice.command(name="lock")
    async def voice_lock(self, ctx: commands.Context):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        await channel.set_permissions(ctx.guild.default_role, connect=False)
        await ctx.send(embed=discord.Embed(description="Canal bloqueado 🔒", color=0x57f287))

    @voice.command(name="unlock")
    async def voice_unlock(self, ctx: commands.Context):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        await channel.set_permissions(ctx.guild.default_role, connect=True)
        await ctx.send(embed=discord.Embed(description="Canal desbloqueado 🔓", color=0x57f287))

    @voice.command(name="hide")
    async def voice_hide(self, ctx: commands.Context):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        await channel.set_permissions(ctx.guild.default_role, view_channel=False)
        await ctx.send(embed=discord.Embed(description="Canal oculto 🙈", color=0x57f287))

    @voice.command(name="unhide")
    async def voice_unhide(self, ctx: commands.Context):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        await channel.set_permissions(ctx.guild.default_role, view_channel=True)
        await ctx.send(embed=discord.Embed(description="Canal visible 👁️", color=0x57f287))

    @voice.command(name="rename")
    async def voice_rename(self, ctx: commands.Context, *, name: str):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        await channel.edit(name=name[:100])
        await ctx.send(embed=discord.Embed(description=f"Canal renombrado a **{name[:100]}**.", color=0x57f287))

    @voice.command(name="limit")
    async def voice_limit(self, ctx: commands.Context, number: int):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        await channel.edit(user_limit=max(0, min(number, 99)))
        await ctx.send(embed=discord.Embed(description=f"Límite ajustado a `{number}`.", color=0x57f287))

    @voice.command(name="kick")
    async def voice_kick(self, ctx: commands.Context, member: discord.Member):
        channel = await self._current_temp_channel(ctx)
        if not channel:
            return
        if member.voice and member.voice.channel and member.voice.channel.id == channel.id:
            await member.move_to(None, reason=f"Kick del VC por {ctx.author}")
            await ctx.send(embed=discord.Embed(description=f"{member.mention} fue sacado del canal.", color=0x57f287))
        else:
            await ctx.send(embed=discord.Embed(description="Ese usuario no está en tu canal.", color=0xed4245))

    @voice.command(name="claim")
    async def voice_claim(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=discord.Embed(description="Debes estar en un canal de voz.", color=0xed4245))
        channel = ctx.author.voice.channel
        temp = _get_temp_channels(ctx.guild.id)
        if str(channel.id) not in temp:
            return await ctx.send(embed=discord.Embed(description="Ese no es un canal temporal.", color=0xed4245))

        owner_id = temp.get(str(channel.id))
        owner_still_here = owner_id and ctx.guild.get_member(int(owner_id)) in channel.members

        if owner_still_here:
            return await ctx.send(embed=discord.Embed(description="El dueño sigue en el canal.", color=0xed4245))

        temp[str(channel.id)] = ctx.author.id
        _save_temp_channels(ctx.guild.id, temp)
        await channel.set_permissions(ctx.author, manage_channels=True, move_members=True, mute_members=True)
        await ctx.send(embed=discord.Embed(description=f"{ctx.author.mention} ahora es el dueño de este canal 👑", color=0x57f287))


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
