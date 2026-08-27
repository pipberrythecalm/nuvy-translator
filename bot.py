import os
import sqlite3
import asyncio
import discord
from discord import app_commands
import argostranslate.package
import argostranslate.translate

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("NUVY_DB_PATH", "nuvy.db")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =========================================================
# BANCO DE DADOS
# =========================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS translation_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            pt_channel_id INTEGER NOT NULL,
            en_channel_id INTEGER NOT NULL,
            es_channel_id INTEGER NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def add_group(guild_id, pt_id, en_id, es_id):
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        INSERT INTO translation_groups (
            guild_id,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        )
        VALUES (?, ?, ?, ?)
        """,
        (guild_id, pt_id, en_id, es_id)
    )

    conn.commit()
    conn.close()


def get_groups(guild_id):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
        """
        SELECT
            id,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        WHERE guild_id = ?
        """,
        (guild_id,)
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def delete_group(guild_id, group_id):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
        """
        DELETE FROM translation_groups
        WHERE guild_id = ? AND id = ?
        """,
        (guild_id, group_id)
    )

    conn.commit()
    deleted = cursor.rowcount
    conn.close()

    return deleted > 0


def get_group_for_channel(guild_id, channel_id):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
        """
        SELECT
            id,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        WHERE guild_id = ?
        AND (
            pt_channel_id = ?
            OR en_channel_id = ?
            OR es_channel_id = ?
        )
        LIMIT 1
        """,
        (
            guild_id,
            channel_id,
            channel_id,
            channel_id
        )
    )

    row = cursor.fetchone()
    conn.close()

    return row


# =========================================================
# ARGOS TRANSLATE
# =========================================================

def install_translation_models():
    print("☁️ Nuvy: verificando modelos de tradução...")

    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()

    required_pairs = [
        ("pt", "en"),
        ("en", "pt"),
        ("es", "en"),
        ("en", "es"),
    ]

    installed_languages = argostranslate.translate.get_installed_languages()

    def pair_exists(from_code, to_code):
        from_lang = next(
            (
                lang for lang in installed_languages
                if lang.code == from_code
            ),
            None
        )

        to_lang = next(
            (
                lang for lang in installed_languages
                if lang.code == to_code
            ),
            None
        )

        if not from_lang or not to_lang:
            return False

        try:
            from_lang.get_translation(to_lang)
            return True
        except Exception:
            return False

    for from_code, to_code in required_pairs:
        if pair_exists(from_code, to_code):
            print(f"✓ Modelo {from_code} → {to_code} já instalado")
            continue

        package = next(
            (
                pkg for pkg in available_packages
                if pkg.from_code == from_code
                and pkg.to_code == to_code
            ),
            None
        )

        if package:
            print(f"☁️ Instalando {from_code} → {to_code}...")

            download_path = package.download()
            argostranslate.package.install_from_path(download_path)

            installed_languages = (
                argostranslate.translate.get_installed_languages()
            )

            print(f"✓ Modelo {from_code} → {to_code} instalado")
        else:
            print(
                f"⚠️ Modelo não encontrado: "
                f"{from_code} → {to_code}"
            )


def translate_direct(text, source, target):
    installed_languages = (
        argostranslate.translate.get_installed_languages()
    )

    source_language = next(
        (
            lang for lang in installed_languages
            if lang.code == source
        ),
        None
    )

    target_language = next(
        (
            lang for lang in installed_languages
            if lang.code == target
        ),
        None
    )

    if not source_language or not target_language:
        raise RuntimeError(
            f"Idioma não instalado: {source} → {target}"
        )

    translation = source_language.get_translation(
        target_language
    )

    return translation.translate(text)


def translate_text(text, source, target):
    if source == target:
        return text

    direct_pairs = {
        ("pt", "en"),
        ("en", "pt"),
        ("es", "en"),
        ("en", "es"),
    }

    if (source, target) in direct_pairs:
        return translate_direct(
            text,
            source,
            target
        )

    # PT ↔ ES passa pelo inglês
    first_step = translate_direct(
        text,
        source,
        "en"
    )

    second_step = translate_direct(
        first_step,
        "en",
        target
    )

    return second_step


# =========================================================
# WEBHOOKS
# =========================================================

async def get_nuvy_webhook(channel):
    webhooks = await channel.webhooks()

    for webhook in webhooks:
        if webhook.name == "Nuvy Translator":
            return webhook

    return await channel.create_webhook(
        name="Nuvy Translator"
    )


async def send_translation(
    target_channel,
    original_message,
    translated_text
):
    webhook = await get_nuvy_webhook(
        target_channel
    )

    await webhook.send(
        content=translated_text,
        username=original_message.author.display_name,
        avatar_url=(
            original_message.author.display_avatar.url
        ),
        allowed_mentions=discord.AllowedMentions.none(),
        wait=True
    )


# =========================================================
# PERMISSÕES DOS COMANDOS
# =========================================================

def can_manage_translation(interaction):
    if not interaction.guild:
        return False

    permissions = interaction.user.guild_permissions

    return (
        permissions.administrator
        or permissions.manage_guild
    )


# =========================================================
# SLASH COMMANDS
# =========================================================

@tree.command(
    name="link",
    description="Connect three channels for automatic translation."
)
@app_commands.describe(
    portugues="Portuguese channel",
    english="English channel",
    espanhol="Spanish channel"
)
async def link(
    interaction: discord.Interaction,
    portugues: discord.TextChannel,
    english: discord.TextChannel,
    espanhol: discord.TextChannel
):
    if not can_manage_translation(interaction):
        await interaction.response.send_message(
            "☁️ You need Manage Server permission to use this command.",
            ephemeral=True
        )
        return

    channels = {
        portugues.id,
        english.id,
        espanhol.id
    }

    if len(channels) != 3:
        await interaction.response.send_message(
            "☁️ Please select three different channels.",
            ephemeral=True
        )
        return

    existing = get_groups(interaction.guild.id)

    used_channels = set()

    for group in existing:
        _, pt_id, en_id, es_id = group

        used_channels.update(
            [pt_id, en_id, es_id]
        )

    if any(channel_id in used_channels for channel_id in channels):
        await interaction.response.send_message(
            "☁️ One of these channels already belongs to another translation group.",
            ephemeral=True
        )
        return

    add_group(
        interaction.guild.id,
        portugues.id,
        english.id,
        espanhol.id
    )

    await interaction.response.send_message(
        (
            "☁️ **Translation group connected!**\n\n"
            f"🇧🇷 {portugues.mention}\n"
            f"🇺🇸 {english.mention}\n"
            f"🇪🇸 {espanhol.mention}"
        )
    )


@tree.command(
    name="groups",
    description="Show all translation groups."
)
async def groups(
    interaction: discord.Interaction
):
    if not interaction.guild:
        return

    groups_list = get_groups(
        interaction.guild.id
    )

    if not groups_list:
        await interaction.response.send_message(
            "☁️ No translation groups are configured.",
            ephemeral=True
        )
        return

    lines = []

    for group in groups_list:
        group_id, pt_id, en_id, es_id = group

        lines.append(
            (
                f"**Group {group_id}**\n"
                f"🇧🇷 <#{pt_id}>\n"
                f"🇺🇸 <#{en_id}>\n"
                f"🇪🇸 <#{es_id}>"
            )
        )

    await interaction.response.send_message(
        "☁️ **Nuvy translation groups**\n\n"
        + "\n\n".join(lines)
    )


@tree.command(
    name="unlink",
    description="Remove a translation group."
)
@app_commands.describe(
    group_id="ID shown by /groups"
)
async def unlink(
    interaction: discord.Interaction,
    group_id: int
):
    if not can_manage_translation(interaction):
        await interaction.response.send_message(
            "☁️ You need Manage Server permission to use this command.",
            ephemeral=True
        )
        return

    deleted = delete_group(
        interaction.guild.id,
        group_id
    )

    if deleted:
        await interaction.response.send_message(
            f"☁️ Translation group {group_id} removed."
        )
    else:
        await interaction.response.send_message(
            "☁️ Translation group not found.",
            ephemeral=True
        )


@tree.command(
    name="nuvy-status",
    description="Check whether Nuvy is online."
)
async def nuvy_status(
    interaction: discord.Interaction
):
    groups_list = get_groups(
        interaction.guild.id
    )

    await interaction.response.send_message(
        (
            "☁️ **Nuvy is online!**\n"
            f"Translation groups: {len(groups_list)}\n"
            "Languages: PT-BR • EN • ES"
        ),
        ephemeral=True
    )


# =========================================================
# DISCORD EVENTS
# =========================================================

@client.event
async def on_ready():
    await tree.sync()

    print("--------------------------------")
    print(f"☁️ Nuvy connected as {client.user}")
    print("PT-BR • EN • ES")
    print("--------------------------------")


@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.webhook_id is not None:
        return

    if not message.guild:
        return

    if not message.content.strip():
        return

    group = get_group_for_channel(
        message.guild.id,
        message.channel.id
    )

    if not group:
        return

    _, pt_id, en_id, es_id = group

    channel_map = {
        "pt": pt_id,
        "en": en_id,
        "es": es_id
    }

    source_language = None

    for language, channel_id in channel_map.items():
        if message.channel.id == channel_id:
            source_language = language
            break

    if not source_language:
        return

    for target_language, target_channel_id in channel_map.items():
        if target_language == source_language:
            continue

        target_channel = client.get_channel(
            target_channel_id
        )

        if not target_channel:
            continue

        try:
            translated = await asyncio.to_thread(
                translate_text,
                message.content,
                source_language,
                target_language
            )

            await send_translation(
                target_channel,
                message,
                translated
            )

        except Exception as error:
            print(
                f"Translation error "
                f"{source_language} → "
                f"{target_language}: {error}"
            )


# =========================================================
# START
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN was not configured."
    )

init_db()
install_translation_models()

client.run(TOKEN)
