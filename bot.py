import os
import sqlite3
import asyncio
from functools import lru_cache

import discord
from discord import app_commands

import argostranslate.package
import argostranslate.translate


# =========================================================
# NUVY ☁️
# PT-BR • EN • ES simultaneous Discord translator
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("NUVY_DB_PATH", "nuvy.db")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =========================================================
# MEMORY CACHES
# =========================================================

# (guild_id, channel_id) -> group data
group_cache = {}

# channel_id -> Discord webhook
webhook_cache = {}

# ("pt", "en") -> Argos translation object
translator_cache = {}


# =========================================================
# DATABASE
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


def load_group_cache():
    global group_cache

    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute(
        """
        SELECT
            id,
            guild_id,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        """
    ).fetchall()

    conn.close()

    group_cache = {}

    for group_id, guild_id, pt_id, en_id, es_id in rows:

        group_data = {
            "id": group_id,
            "pt": pt_id,
            "en": en_id,
            "es": es_id,
        }

        group_cache[(guild_id, pt_id)] = group_data
        group_cache[(guild_id, en_id)] = group_data
        group_cache[(guild_id, es_id)] = group_data

    print(f"☁️ Groups loaded into memory: {len(rows)}")


def add_group(guild_id, pt_id, en_id, es_id):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
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

    group_id = cursor.lastrowid

    conn.commit()
    conn.close()

    load_group_cache()

    return group_id


def get_groups(guild_id):
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute(
        """
        SELECT
            id,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        WHERE guild_id = ?
        ORDER BY id
        """,
        (guild_id,)
    ).fetchall()

    conn.close()

    return rows


def delete_group(guild_id, group_id):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
        """
        DELETE FROM translation_groups
        WHERE guild_id = ?
        AND id = ?
        """,
        (guild_id, group_id)
    )

    conn.commit()

    deleted = cursor.rowcount > 0

    conn.close()

    if deleted:
        load_group_cache()

    return deleted


# =========================================================
# ARGOS TRANSLATE
# =========================================================

def install_argos_models():

    print("☁️ Updating Argos package index...")

    argostranslate.package.update_package_index()

    available_packages = (
        argostranslate.package.get_available_packages()
    )

    installed_packages = (
        argostranslate.package.get_installed_packages()
    )

    # These four MUST exist.
    required_pairs = [
        ("pt", "en"),
        ("en", "pt"),
        ("es", "en"),
        ("en", "es"),
    ]

    def is_installed(source, target):

        return any(
            package.from_code == source
            and package.to_code == target
            for package in installed_packages
        )

    for source, target in required_pairs:

        if is_installed(source, target):

            print(
                f"✓ Argos package already installed: "
                f"{source} → {target}"
            )

            continue

        package = next(
            (
                p for p in available_packages
                if p.from_code == source
                and p.to_code == target
            ),
            None
        )

        if package is None:

            raise RuntimeError(
                f"Required Argos package not found: "
                f"{source} → {target}"
            )

        print(
            f"☁️ Installing Argos package: "
            f"{source} → {target}"
        )

        download_path = package.download()

        argostranslate.package.install_from_path(
            download_path
        )

        installed_packages = (
            argostranslate.package.get_installed_packages()
        )

        print(
            f"✓ Installed: {source} → {target}"
        )

    # Optional direct PT ↔ ES models.
    # If Argos offers them, we install them.
    optional_pairs = [
        ("pt", "es"),
        ("es", "pt"),
    ]

    for source, target in optional_pairs:

        if is_installed(source, target):
            continue

        package = next(
            (
                p for p in available_packages
                if p.from_code == source
                and p.to_code == target
            ),
            None
        )

        if package:

            try:

                print(
                    f"☁️ Installing optional direct model: "
                    f"{source} → {target}"
                )

                download_path = package.download()

                argostranslate.package.install_from_path(
                    download_path
                )

                installed_packages = (
                    argostranslate.package
                    .get_installed_packages()
                )

                print(
                    f"✓ Direct model installed: "
                    f"{source} → {target}"
                )

            except Exception as error:

                print(
                    f"⚠️ Optional model "
                    f"{source} → {target} skipped: "
                    f"{error}"
                )


def build_translator_cache():

    global translator_cache

    translator_cache = {}

    languages = (
        argostranslate.translate
        .get_installed_languages()
    )

    language_map = {
        language.code: language
        for language in languages
    }

    pairs = [
        ("pt", "en"),
        ("en", "pt"),
        ("en", "es"),
        ("es", "en"),
        ("pt", "es"),
        ("es", "pt"),
    ]

    for source, target in pairs:

        source_language = language_map.get(source)
        target_language = language_map.get(target)

        if not source_language or not target_language:
            continue

        try:

            translation = (
                source_language
                .get_translation(target_language)
            )

            translator_cache[
                (source, target)
            ] = translation

            print(
                f"✓ Translator ready: "
                f"{source} → {target}"
            )

        except Exception:

            pass


def translate_direct(text, source, target):

    translator = translator_cache.get(
        (source, target)
    )

    if translator is None:

        raise RuntimeError(
            f"Translator unavailable: "
            f"{source} → {target}"
        )

    return translator.translate(text)


@lru_cache(maxsize=2000)
def translate_cached(text, source, target):

    if source == target:
        return text

    # Direct translation if available.
    direct = translator_cache.get(
        (source, target)
    )

    if direct is not None:

        return direct.translate(text)

    # PT ↔ ES fallback through English.
    if source == "pt" and target == "es":

        english = translate_direct(
            text,
            "pt",
            "en"
        )

        return translate_direct(
            english,
            "en",
            "es"
        )

    if source == "es" and target == "pt":

        english = translate_direct(
            text,
            "es",
            "en"
        )

        return translate_direct(
            english,
            "en",
            "pt"
        )

    raise RuntimeError(
        f"Translation path unavailable: "
        f"{source} → {target}"
    )


# =========================================================
# WEBHOOKS
# =========================================================

async def get_nuvy_webhook(channel):

    cached = webhook_cache.get(channel.id)

    if cached is not None:
        return cached

    webhooks = await channel.webhooks()

    for webhook in webhooks:

        if webhook.name == "Nuvy Translator":

            webhook_cache[channel.id] = webhook

            return webhook

    webhook = await channel.create_webhook(
        name="Nuvy Translator"
    )

    webhook_cache[channel.id] = webhook

    return webhook


async def warm_webhook(channel):

    try:

        await get_nuvy_webhook(channel)

    except Exception as error:

        print(
            f"⚠️ Could not prepare webhook "
            f"for #{channel.name}: {error}"
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
            original_message.author
            .display_avatar.url
        ),
        allowed_mentions=(
            discord.AllowedMentions.none()
        ),
        wait=False
    )


# =========================================================
# COMMAND PERMISSIONS
# =========================================================

def can_manage_translation(interaction):

    if interaction.guild is None:
        return False

    permissions = (
        interaction.user.guild_permissions
    )

    return (
        permissions.administrator
        or permissions.manage_guild
    )


# =========================================================
# /LINK
# =========================================================

@tree.command(
    name="link",
    description=(
        "Connect PT-BR, English and Spanish channels."
    )
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
            (
                "☁️ You need Manage Server permission "
                "to use this command."
            ),
            ephemeral=True
        )

        return

    selected_ids = {
        portugues.id,
        english.id,
        espanhol.id
    }

    if len(selected_ids) != 3:

        await interaction.response.send_message(
            (
                "☁️ Please select three "
                "different channels."
            ),
            ephemeral=True
        )

        return

    # Prevent a channel from belonging to two groups.
    for channel_id in selected_ids:

        if (
            interaction.guild.id,
            channel_id
        ) in group_cache:

            await interaction.response.send_message(
                (
                    "☁️ One of these channels "
                    "already belongs to another "
                    "translation group."
                ),
                ephemeral=True
            )

            return

    group_id = add_group(
        interaction.guild.id,
        portugues.id,
        english.id,
        espanhol.id
    )

    await interaction.response.defer()

    # Prepare all webhooks immediately.
    # This avoids delay on the first real message.
    await asyncio.gather(
        warm_webhook(portugues),
        warm_webhook(english),
        warm_webhook(espanol)
    )

    await interaction.followup.send(
        (
            f"☁️ **Translation group {group_id} connected!**\n\n"
            f"🇧🇷 {portugues.mention}\n"
            f"🇺🇸 {english.mention}\n"
            f"🇪🇸 {espanol.mention}"
        )
    )


# =========================================================
# /GROUPS
# =========================================================

@tree.command(
    name="groups",
    description="Show all Nuvy translation groups."
)
async def groups(
    interaction: discord.Interaction
):

    if interaction.guild is None:
        return

    groups_list = get_groups(
        interaction.guild.id
    )

    if not groups_list:

        await interaction.response.send_message(
            (
                "☁️ No translation groups "
                "are configured."
            ),
            ephemeral=True
        )

        return

    blocks = []

    for (
        group_id,
        pt_id,
        en_id,
        es_id
    ) in groups_list:

        blocks.append(
            (
                f"**Group {group_id}**\n"
                f"🇧🇷 <#{pt_id}>\n"
                f"🇺🇸 <#{en_id}>\n"
                f"🇪🇸 <#{es_id}>"
            )
        )

    await interaction.response.send_message(
        (
            "☁️ **Nuvy Translation Groups**\n\n"
            + "\n\n".join(blocks)
        )
    )


# =========================================================
# /UNLINK
# =========================================================

@tree.command(
    name="unlink",
    description="Remove a Nuvy translation group."
)
@app_commands.describe(
    group_id="Group ID shown by /groups"
)
async def unlink(
    interaction: discord.Interaction,
    group_id: int
):

    if not can_manage_translation(interaction):

        await interaction.response.send_message(
            (
                "☁️ You need Manage Server permission "
                "to use this command."
            ),
            ephemeral=True
        )

        return

    deleted = delete_group(
        interaction.guild.id,
        group_id
    )

    if deleted:

        await interaction.response.send_message(
            (
                f"☁️ Translation group "
                f"{group_id} removed."
            )
        )

    else:

        await interaction.response.send_message(
            (
                "☁️ Translation group "
                "not found."
            ),
            ephemeral=True
        )


# =========================================================
# /NUVY-STATUS
# =========================================================

@tree.command(
    name="nuvy-status",
    description="Check Nuvy's translation status."
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
            "Languages: PT-BR • EN • ES\n"
            "Translator: Argos Translate"
        ),
        ephemeral=True
    )


# =========================================================
# MESSAGE TRANSLATION
# =========================================================

async def process_target(
    original_message,
    source_language,
    target_language,
    target_channel_id
):

    target_channel = client.get_channel(
        target_channel_id
    )

    if target_channel is None:

        print(
            f"⚠️ Channel not found: "
            f"{target_channel_id}"
        )

        return

    try:

        translated = await asyncio.to_thread(
            translate_cached,
            original_message.content,
            source_language,
            target_language
        )

        await send_translation(
            target_channel,
            original_message,
            translated
        )

        print(
            f"✓ {source_language} → "
            f"{target_language}"
        )

    except Exception as error:

        print(
            f"❌ Translation error "
            f"{source_language} → "
            f"{target_language}: "
            f"{error}"
        )


@client.event
async def on_message(message):

    # Prevent webhook/bot loops.
    if message.author.bot:
        return

    if message.webhook_id is not None:
        return

    if message.guild is None:
        return

    if not message.content.strip():
        return

    group = group_cache.get(
        (
            message.guild.id,
            message.channel.id
        )
    )

    if group is None:
        return

    source_language = None

    for language in ("pt", "en", "es"):

        if group[language] == message.channel.id:

            source_language = language
            break

    if source_language is None:
        return

    tasks = []

    for target_language in ("pt", "en", "es"):

        if target_language == source_language:
            continue

        tasks.append(
            process_target(
                message,
                source_language,
                target_language,
                group[target_language]
            )
        )

    # Both translations happen simultaneously.
    await asyncio.gather(
        *tasks,
        return_exceptions=True
    )


# =========================================================
# READY
# =========================================================

@client.event
async def on_ready():

    load_group_cache()

    await tree.sync()

    print("--------------------------------")
    print(f"☁️ Nuvy connected as {client.user}")
    print("PT-BR • EN • ES")
    print(
        f"Webhooks cached: "
        f"{len(webhook_cache)}"
    )
    print("--------------------------------")


# =========================================================
# START
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN was not configured."
    )


init_db()

install_argos_models()

build_translator_cache()

load_group_cache()

client.run(TOKEN)
