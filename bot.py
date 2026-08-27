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
# Discord Translator
# PT-BR • EN • ES
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("NUVY_DB_PATH", "nuvy.db")


# =========================================================
# SERVIDORES AUTORIZADOS
# =========================================================

ALLOWED_GUILDS = {
    1479635560845938688,  # THE
    1526568308202274846,  # Stormy
    1532893718846378014,  # Futebol
}


# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =========================================================
# CACHE
# =========================================================

# (guild_id, channel_id) -> informações do grupo
group_cache = {}

# channel_id -> webhook
webhook_cache = {}

# ("pt", "en") -> tradutor Argos carregado
translator_cache = {}


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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS message_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            pt_message_id INTEGER,
            en_message_id INTEGER,
            es_message_id INTEGER
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

    print(f"☁️ Translation groups loaded: {len(rows)}")


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
        (
            guild_id,
            pt_id,
            en_id,
            es_id
        )
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
        (
            guild_id,
            group_id
        )
    )

    conn.commit()

    deleted = cursor.rowcount > 0

    conn.close()

    if deleted:
        load_group_cache()

    return deleted


def save_message_link(
    guild_id,
    group_id,
    pt_message_id=None,
    en_message_id=None,
    es_message_id=None
):
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        INSERT INTO message_links (
            guild_id,
            group_id,
            pt_message_id,
            en_message_id,
            es_message_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            group_id,
            pt_message_id,
            en_message_id,
            es_message_id
        )
    )

    conn.commit()
    conn.close()


def get_message_link(guild_id, message_id):
    conn = sqlite3.connect(DB_PATH)

    row = conn.execute(
        """
        SELECT
            group_id,
            pt_message_id,
            en_message_id,
            es_message_id
        FROM message_links
        WHERE guild_id = ?
        AND (
            pt_message_id = ?
            OR en_message_id = ?
            OR es_message_id = ?
        )
        LIMIT 1
        """,
        (
            guild_id,
            message_id,
            message_id,
            message_id
        )
    ).fetchone()

    conn.close()

    if row is None:
        return None

    group_id, pt_id, en_id, es_id = row

    return {
        "group_id": group_id,
        "pt": pt_id,
        "en": en_id,
        "es": es_id
    }


# =========================================================
# ARGOS TRANSLATE
# =========================================================

def install_argos_models():

    print("☁️ Checking translation models...")

    argostranslate.package.update_package_index()

    available_packages = (
        argostranslate.package.get_available_packages()
    )

    installed_packages = (
        argostranslate.package.get_installed_packages()
    )

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
                f"✓ Model already installed: "
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
                f"Required translation model not found: "
                f"{source} → {target}"
            )

        print(
            f"☁️ Installing model: "
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
            f"✓ Installed: "
            f"{source} → {target}"
        )

    # Tenta instalar modelos PT ↔ ES diretamente.
    # Caso não existam, Nuvy usa inglês como ponte.

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

        if package is None:
            continue

        try:

            print(
                f"☁️ Installing optional model: "
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
                f"✓ Optional model installed: "
                f"{source} → {target}"
            )

        except Exception as error:

            print(
                f"⚠️ Optional model skipped: "
                f"{source} → {target}: {error}"
            )


def build_translator_cache():

    global translator_cache

    translator_cache = {}

    languages = (
        argostranslate.translate.get_installed_languages()
    )

    language_map = {
        language.code: language
        for language in languages
    }

    pairs = [
        ("pt", "en"),
        ("en", "pt"),
        ("es", "en"),
        ("en", "es"),
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
                source_language.get_translation(
                    target_language
                )
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


@lru_cache(maxsize=3000)
def translate_cached(text, source, target):

    if source == target:
        return text

    direct = translator_cache.get(
        (source, target)
    )

    if direct is not None:
        return direct.translate(text)

    # PT → ES via inglês
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

    # ES → PT via inglês
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
            f"⚠️ Webhook error in "
            f"#{channel.name}: {error}"
        )


# =========================================================
# REPLIES
# =========================================================

async def get_reply_information(
    original_message,
    target_language,
    target_channel
):

    if original_message.reference is None:
        return None

    referenced_id = (
        original_message.reference.message_id
    )

    if referenced_id is None:
        return None

    link = get_message_link(
        original_message.guild.id,
        referenced_id
    )

    if link is None:
        return None

    target_message_id = link.get(
        target_language
    )

    if target_message_id is None:
        return None

    try:

        target_message = (
            await target_channel.fetch_message(
                target_message_id
            )
        )

        return target_message

    except Exception:
        return None


async def send_translation(
    target_channel,
    original_message,
    translated_text,
    target_language
):

    webhook = await get_nuvy_webhook(
        target_channel
    )

    replied_message = (
        await get_reply_information(
            original_message,
            target_language,
            target_channel
        )
    )

    # Webhooks não oferecem reply nativo confiável
    # em todas as versões do discord.py.
    # Portanto usamos uma prévia visual quando necessário.

    if replied_message is not None:

        reply_author = (
            replied_message.author.display_name
        )

        reply_preview = (
            replied_message.content.strip()
            if replied_message.content
            else "message"
        )

        if len(reply_preview) > 100:
            reply_preview = (
                reply_preview[:100] + "…"
            )

        translated_text = (
            f"↪️ **{reply_author}:** "
            f"{reply_preview}\n"
            f"{translated_text}"
        )

    sent_message = await webhook.send(
        content=translated_text,
        username=(
            original_message.author.display_name
        ),
        avatar_url=(
            original_message.author
            .display_avatar.url
        ),
        allowed_mentions=(
            discord.AllowedMentions.none()
        ),
        wait=True
    )

    return sent_message


# =========================================================
# PERMISSÕES
# =========================================================

def guild_allowed(interaction):

    return (
        interaction.guild is not None
        and interaction.guild.id
        in ALLOWED_GUILDS
    )


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


async def reject_unauthorized_guild(
    interaction
):

    await interaction.response.send_message(
        (
            "☁️ Nuvy is not authorized "
            "to work on this server."
        ),
        ephemeral=True
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

    if not guild_allowed(interaction):

        await reject_unauthorized_guild(
            interaction
        )

        return

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

    # Cria/cacheia os três webhooks imediatamente.
    await asyncio.gather(
        warm_webhook(portugues),
        warm_webhook(english),
        warm_webhook(espanol)
    )

    await interaction.followup.send(
        (
            f"☁️ **Translation group "
            f"{group_id} connected!**\n\n"
            f"🇧🇷 {portugues.mention}\n"
            f"🇺🇸 {english.mention}\n"
            f"🇪🇸 {espanhol.mention}"
        )
    )


# =========================================================
# /GROUPS
# =========================================================

@tree.command(
    name="groups",
    description=(
        "Show all Nuvy translation groups."
    )
)
async def groups(
    interaction: discord.Interaction
):

    if not guild_allowed(interaction):

        await reject_unauthorized_guild(
            interaction
        )

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
    description=(
        "Remove a Nuvy translation group."
    )
)
@app_commands.describe(
    group_id="Group ID shown by /groups"
)
async def unlink(
    interaction: discord.Interaction,
    group_id: int
):

    if not guild_allowed(interaction):

        await reject_unauthorized_guild(
            interaction
        )

        return

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
    description=(
        "Check Nuvy's translation status."
    )
)
async def nuvy_status(
    interaction: discord.Interaction
):

    if not guild_allowed(interaction):

        await reject_unauthorized_guild(
            interaction
        )

        return

    groups_list = get_groups(
        interaction.guild.id
    )

    await interaction.response.send_message(
        (
            "☁️ **Nuvy is online!**\n"
            f"Translation groups: "
            f"{len(groups_list)}\n"
            "Languages: PT-BR • EN • ES\n"
            "Replies: enabled\n"
            "Server: authorized"
        ),
        ephemeral=True
    )


# =========================================================
# PROCESSAR UMA TRADUÇÃO
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
            f"⚠️ Target channel not found: "
            f"{target_channel_id}"
        )

        return None

    try:

        translated = await asyncio.to_thread(
            translate_cached,
            original_message.content,
            source_language,
            target_language
        )

        sent_message = await send_translation(
            target_channel,
            original_message,
            translated,
            target_language
        )

        print(
            f"✓ Translation: "
            f"{source_language} → "
            f"{target_language}"
        )

        return (
            target_language,
            sent_message.id
        )

    except Exception as error:

        print(
            f"❌ Translation error "
            f"{source_language} → "
            f"{target_language}: "
            f"{error}"
        )

        return None


# =========================================================
# MENSAGENS
# =========================================================

@client.event
async def on_message(message):

    # Ignora bots
    if message.author.bot:
        return

    # Ignora os próprios webhooks
    if message.webhook_id is not None:
        return

    # Ignora DMs
    if message.guild is None:
        return

    # BLOQUEIA servidores não autorizados
    if message.guild.id not in ALLOWED_GUILDS:
        return

    # Por enquanto traduz apenas mensagens com texto
    if not message.content.strip():
        return

    group = group_cache.get(
        (
            message.guild.id,
            message.channel.id
        )
    )

    # Canal não pertence a nenhum grupo
    if group is None:
        return

    source_language = None

    for language in (
        "pt",
        "en",
        "es"
    ):

        if (
            group[language]
            == message.channel.id
        ):

            source_language = language
            break

    if source_language is None:
        return

    message_ids = {
        "pt": None,
        "en": None,
        "es": None
    }

    # Salva a mensagem original
    message_ids[
        source_language
    ] = message.id

    tasks = []

    # Dispara as duas traduções simultaneamente
    for target_language in (
        "pt",
        "en",
        "es"
    ):

        if (
            target_language
            == source_language
        ):
            continue

        tasks.append(
            process_target(
                message,
                source_language,
                target_language,
                group[target_language]
            )
        )

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True
    )

    for result in results:

        if (
            isinstance(result, tuple)
            and len(result) == 2
        ):

            language, message_id = result

            message_ids[
                language
            ] = message_id

    # Vincula as três versões da mensagem
    save_message_link(
        guild_id=message.guild.id,
        group_id=group["id"],
        pt_message_id=message_ids["pt"],
        en_message_id=message_ids["en"],
        es_message_id=message_ids["es"]
    )


# =========================================================
# SERVIDOR NÃO AUTORIZADO
# =========================================================

@client.event
async def on_guild_join(guild):

    if guild.id in ALLOWED_GUILDS:
        return

    print(
        f"⚠️ Unauthorized server: "
        f"{guild.name} ({guild.id})"
    )

    try:

        await guild.leave()

        print(
            f"☁️ Nuvy left unauthorized server: "
            f"{guild.name}"
        )

    except Exception as error:

        print(
            f"❌ Could not leave server: "
            f"{error}"
        )


# =========================================================
# READY
# =========================================================

@client.event
async def on_ready():

    load_group_cache()

    await tree.sync()

    print("")
    print("================================")
    print("☁️ NUVY ONLINE")
    print(f"Logged in as: {client.user}")
    print("Languages: PT-BR • EN • ES")
    print("Replies: enabled")
    print("Allowed servers: 3")
    print(
        f"Translation groups in memory: "
        f"{len(group_cache) // 3}"
    )
    print("================================")
    print("")


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
