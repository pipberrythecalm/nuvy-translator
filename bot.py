import os
import sys
import json
import sqlite3
import asyncio

import discord
from discord import app_commands


# =========================================================
# NUVY ☁️ — ULTRA ECONOMY
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("NUVY_DB_PATH", "/data/nuvy.db")
ARGOS_PACKAGES_DIR = os.getenv(
    "ARGOS_PACKAGES_DIR",
    "/data/argos-packages"
)

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

group_cache = {}
webhook_cache = {}

# Só um Argos pesado por vez.
translation_semaphore = asyncio.Semaphore(1)


# =========================================================
# DATABASE
# =========================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS translation_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            pt_channel_id INTEGER NOT NULL,
            en_channel_id INTEGER NOT NULL,
            es_channel_id INTEGER NOT NULL
        )
    """)

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(translation_groups)"
        ).fetchall()
    }

    if "name" not in columns:
        conn.execute("""
            ALTER TABLE translation_groups
            ADD COLUMN name TEXT
        """)

    conn.execute("""
        UPDATE translation_groups
        SET name = 'Group ' || id
        WHERE name IS NULL OR TRIM(name) = ''
    """)

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_translation_group_name
        ON translation_groups(
            guild_id,
            name COLLATE NOCASE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            pt_message_id INTEGER,
            en_message_id INTEGER,
            es_message_id INTEGER
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# GROUPS
# =========================================================

def load_group_cache():
    global group_cache

    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute("""
        SELECT
            id,
            guild_id,
            name,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
    """).fetchall()

    conn.close()

    group_cache = {}

    for group_id, guild_id, name, pt_id, en_id, es_id in rows:
        data = {
            "id": group_id,
            "name": name,
            "pt": pt_id,
            "en": en_id,
            "es": es_id,
        }

        group_cache[(guild_id, pt_id)] = data
        group_cache[(guild_id, en_id)] = data
        group_cache[(guild_id, es_id)] = data

    print(f"☁️ Groups loaded: {len(rows)}")


def get_groups(guild_id):
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute("""
        SELECT
            id,
            name,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        WHERE guild_id = ?
        ORDER BY name COLLATE NOCASE
    """, (guild_id,)).fetchall()

    conn.close()
    return rows


def group_name_exists(guild_id, name):
    conn = sqlite3.connect(DB_PATH)

    row = conn.execute("""
        SELECT id
        FROM translation_groups
        WHERE guild_id = ?
        AND name = ? COLLATE NOCASE
        LIMIT 1
    """, (guild_id, name.strip())).fetchone()

    conn.close()
    return row is not None


def add_group(guild_id, name, pt_id, en_id, es_id):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute("""
        INSERT INTO translation_groups (
            guild_id,
            name,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        guild_id,
        name.strip(),
        pt_id,
        en_id,
        es_id
    ))

    group_id = cursor.lastrowid

    conn.commit()
    conn.close()

    load_group_cache()
    return group_id


def delete_group_by_name(guild_id, group_name):
    conn = sqlite3.connect(DB_PATH)

    row = conn.execute("""
        SELECT id, name
        FROM translation_groups
        WHERE guild_id = ?
        AND name = ? COLLATE NOCASE
        LIMIT 1
    """, (
        guild_id,
        group_name.strip()
    )).fetchone()

    if row is None:
        conn.close()
        return None

    group_id, real_name = row

    conn.execute("""
        DELETE FROM message_links
        WHERE guild_id = ? AND group_id = ?
    """, (
        guild_id,
        group_id
    ))

    conn.execute("""
        DELETE FROM translation_groups
        WHERE guild_id = ? AND id = ?
    """, (
        guild_id,
        group_id
    ))

    conn.commit()
    conn.close()

    load_group_cache()
    return real_name


# =========================================================
# MESSAGE LINKS
# =========================================================

def save_message_link(
    guild_id,
    group_id,
    pt_message_id=None,
    en_message_id=None,
    es_message_id=None
):
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        INSERT INTO message_links (
            guild_id,
            group_id,
            pt_message_id,
            en_message_id,
            es_message_id
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        guild_id,
        group_id,
        pt_message_id,
        en_message_id,
        es_message_id
    ))

    conn.commit()
    conn.close()


def get_message_link(guild_id, message_id):
    conn = sqlite3.connect(DB_PATH)

    row = conn.execute("""
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
    """, (
        guild_id,
        message_id,
        message_id,
        message_id
    )).fetchone()

    conn.close()

    if row is None:
        return None

    return {
        "group_id": row[0],
        "pt": row[1],
        "en": row[2],
        "es": row[3]
    }


# =========================================================
# ARGOS WORKER
# =========================================================

def worker_environment():
    env = os.environ.copy()

    env["ARGOS_PACKAGES_DIR"] = ARGOS_PACKAGES_DIR
    env["ARGOS_DEVICE_TYPE"] = "cpu"
    env["ARGOS_INTER_THREADS"] = "1"
    env["ARGOS_INTRA_THREADS"] = "1"
    env["ARGOS_BATCH_SIZE"] = "1"

    return env


async def translate_message(text, source_language):
    async with translation_semaphore:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "translate_worker.py",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=worker_environment()
        )

        request = {
            "text": text,
            "source": source_language
        }

        stdout, stderr = await process.communicate(
            json.dumps(
                request,
                ensure_ascii=False
            ).encode("utf-8")
        )

        if process.returncode != 0:
            error_text = stderr.decode(
                "utf-8",
                errors="replace"
            )

            raise RuntimeError(
                f"Translation worker failed: {error_text}"
            )

        response_text = stdout.decode(
            "utf-8",
            errors="replace"
        ).strip()

        if not response_text:
            raise RuntimeError(
                "Translation worker returned an empty response."
            )

        try:
            result = json.loads(response_text)

        except json.JSONDecodeError as error:
            raise RuntimeError(
                "Invalid response from translation worker: "
                f"{response_text[:300]}"
            ) from error

        if "error" in result:
            raise RuntimeError(result["error"])

        return result


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


async def prepare_group_webhooks(
    portugues,
    english,
    espanhol
):
    await asyncio.gather(
        warm_webhook(portugues),
        warm_webhook(english),
        warm_webhook(espanhol)
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

    target_id = link.get(target_language)

    if target_id is None:
        return None

    try:
        return await target_channel.fetch_message(
            target_id
        )

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

    replied = await get_reply_information(
        original_message,
        target_language,
        target_channel
    )

    if replied is not None:
        author = replied.author.display_name

        preview = (
            replied.content.strip()
            if replied.content
            else "message"
        )

        if len(preview) > 120:
            preview = preview[:120] + "…"

        translated_text = (
            f"↪️ **{author}:** {preview}\n"
            f"{translated_text}"
        )

    return await webhook.send(
        content=translated_text,
        username=original_message.author.display_name,
        avatar_url=original_message.author.display_avatar.url,
        allowed_mentions=discord.AllowedMentions.none(),
        wait=True
    )


# =========================================================
# PERMISSIONS
# =========================================================

def guild_allowed(interaction):
    return (
        interaction.guild is not None
        and interaction.guild.id in ALLOWED_GUILDS
    )


def can_manage_translation(interaction):
    if interaction.guild is None:
        return False

    permissions = interaction.user.guild_permissions

    return (
        permissions.administrator
        or permissions.manage_guild
    )


async def reject_unauthorized_guild(interaction):
    await interaction.response.send_message(
        "☁️ Nuvy is not authorized to work on this server.",
        ephemeral=True
    )


# =========================================================
# AUTOCOMPLETE
# =========================================================

async def group_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    if (
        interaction.guild is None
        or interaction.guild.id not in ALLOWED_GUILDS
    ):
        return []

    groups = get_groups(interaction.guild.id)
    current_lower = current.lower().strip()

    choices = []

    for _id, name, _pt, _en, _es in groups:
        if (
            not current_lower
            or current_lower in name.lower()
        ):
            choices.append(
                app_commands.Choice(
                    name=name,
                    value=name
                )
            )

    return choices[:25]


# =========================================================
# /LINK
# =========================================================

@tree.command(
    name="link",
    description="Create a translation group."
)
@app_commands.describe(
    nome="Name of the translation group",
    portugues="Portuguese channel",
    english="English channel",
    espanhol="Spanish channel"
)
async def link(
    interaction: discord.Interaction,
    nome: str,
    portugues: discord.TextChannel,
    english: discord.TextChannel,
    espanhol: discord.TextChannel
):
    if not guild_allowed(interaction):
        await reject_unauthorized_guild(interaction)
        return

    if not can_manage_translation(interaction):
        await interaction.response.send_message(
            "☁️ You need Manage Server permission to use this command.",
            ephemeral=True
        )
        return

    clean_name = nome.strip()

    if len(clean_name) < 2:
        await interaction.response.send_message(
            "☁️ Please choose a group name.",
            ephemeral=True
        )
        return

    if len(clean_name) > 40:
        await interaction.response.send_message(
            "☁️ Group names can have up to 40 characters.",
            ephemeral=True
        )
        return

    if group_name_exists(
        interaction.guild.id,
        clean_name
    ):
        await interaction.response.send_message(
            f"☁️ A group named **{clean_name}** already exists.",
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
            "☁️ Please choose three different channels.",
            ephemeral=True
        )
        return

    for channel_id in selected_ids:
        existing = group_cache.get(
            (interaction.guild.id, channel_id)
        )

        if existing is not None:
            await interaction.response.send_message(
                (
                    "☁️ One of these channels already belongs "
                    f"to **{existing['name']}**."
                ),
                ephemeral=True
            )
            return

    add_group(
        interaction.guild.id,
        clean_name,
        portugues.id,
        english.id,
        espanhol.id
    )

    # Responde antes de preparar webhooks.
    await interaction.response.send_message(
        (
            f"☁️ **{clean_name} connected!**\n\n"
            f"🇧🇷 {portugues.mention}\n"
            f"🇺🇸 {english.mention}\n"
            f"🇪🇸 {espanhol.mention}"
        )
    )

    asyncio.create_task(
        prepare_group_webhooks(
            portugues,
            english,
            espanhol
        )
    )


# =========================================================
# /GROUPS
# =========================================================

@tree.command(
    name="groups",
    description="Show translation groups."
)
async def groups(interaction: discord.Interaction):
    if not guild_allowed(interaction):
        await reject_unauthorized_guild(interaction)
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

    blocks = []

    for _id, name, pt_id, en_id, es_id in groups_list:
        blocks.append(
            (
                f"### ☁️ {name}\n"
                f"🇧🇷 <#{pt_id}>\n"
                f"🇺🇸 <#{en_id}>\n"
                f"🇪🇸 <#{es_id}>"
            )
        )

    await interaction.response.send_message(
        "## ☁️ Nuvy Translation Groups\n\n"
        + "\n\n".join(blocks)
    )


# =========================================================
# /UNLINK
# =========================================================

@tree.command(
    name="unlink",
    description="Remove a translation group."
)
@app_commands.describe(
    grupo="Choose the translation group"
)
@app_commands.autocomplete(
    grupo=group_autocomplete
)
async def unlink(
    interaction: discord.Interaction,
    grupo: str
):
    if not guild_allowed(interaction):
        await reject_unauthorized_guild(interaction)
        return

    if not can_manage_translation(interaction):
        await interaction.response.send_message(
            "☁️ You need Manage Server permission to use this command.",
            ephemeral=True
        )
        return

    removed = delete_group_by_name(
        interaction.guild.id,
        grupo
    )

    if removed is None:
        await interaction.response.send_message(
            f"☁️ I couldn't find **{grupo}**.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"☁️ Translation group **{removed}** removed."
    )


# =========================================================
# /NUVY-STATUS
# =========================================================

@tree.command(
    name="nuvy-status",
    description="Check Nuvy's status."
)
async def nuvy_status(
    interaction: discord.Interaction
):
    if not guild_allowed(interaction):
        await reject_unauthorized_guild(interaction)
        return

    groups_list = get_groups(
        interaction.guild.id
    )

    await interaction.response.send_message(
        (
            "☁️ **Nuvy is online!**\n"
            f"Translation groups: {len(groups_list)}\n"
            "Languages: PT-BR • EN • ES\n"
            "Mode: Ultra Economy\n"
            "Translation workers: 1\n"
            "PT ↔ ES: via English\n"
            "Replies: enabled\n"
            "Server: authorized"
        ),
        ephemeral=True
    )


# =========================================================
# PROCESS MESSAGE
# =========================================================

async def process_message(
    message,
    source_language,
    group
):
    try:
        translations = await translate_message(
            message.content,
            source_language
        )

    except Exception as error:
        print(
            f"❌ Translation worker error: {error}"
        )
        return

    message_ids = {
        "pt": None,
        "en": None,
        "es": None
    }

    message_ids[source_language] = message.id

    tasks = []
    target_languages = []

    for target_language in ("pt", "en", "es"):
        if target_language == source_language:
            continue

        translated_text = translations.get(
            target_language
        )

        if not translated_text:
            continue

        target_channel = client.get_channel(
            group[target_language]
        )

        if target_channel is None:
            continue

        target_languages.append(target_language)

        tasks.append(
            send_translation(
                target_channel,
                message,
                translated_text,
                target_language
            )
        )

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True
    )

    for language, result in zip(
        target_languages,
        results
    ):
        if isinstance(result, Exception):
            print(
                f"❌ Send error {language}: {result}"
            )
            continue

        message_ids[language] = result.id

    save_message_link(
        guild_id=message.guild.id,
        group_id=group["id"],
        pt_message_id=message_ids["pt"],
        en_message_id=message_ids["en"],
        es_message_id=message_ids["es"]
    )


# =========================================================
# ON MESSAGE
# =========================================================

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.webhook_id is not None:
        return

    if message.guild is None:
        return

    if message.guild.id not in ALLOWED_GUILDS:
        return

    if not message.content.strip():
        return

    group = group_cache.get(
        (message.guild.id, message.channel.id)
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

    asyncio.create_task(
        process_message(
            message,
            source_language,
            group
        )
    )


# =========================================================
# UNAUTHORIZED SERVER
# =========================================================

@client.event
async def on_guild_join(guild):
    if guild.id in ALLOWED_GUILDS:
        return

    try:
        await guild.leave()
        print(
            f"☁️ Left unauthorized server: {guild.name}"
        )

    except Exception as error:
        print(
            f"❌ Leave error: {error}"
        )


# =========================================================
# READY
# =========================================================

has_synced = False


@client.event
async def on_ready():
    global has_synced

    load_group_cache()

    if not has_synced:
        await tree.sync()
        has_synced = True

    unique_groups = {
        group["id"]
        for group in group_cache.values()
    }

    print("")
    print("================================")
    print("☁️ NUVY ONLINE")
    print("MODE: ULTRA ECONOMY")
    print(f"Logged in as: {client.user}")
    print("Argos in main process: NO")
    print("Translation workers: MAX 1")
    print("PT ↔ ES: via English")
    print("Allowed servers: 3")
    print(
        f"Translation groups: {len(unique_groups)}"
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

os.makedirs(
    os.path.dirname(DB_PATH) or ".",
    exist_ok=True
)

os.makedirs(
    ARGOS_PACKAGES_DIR,
    exist_ok=True
)

init_db()
load_group_cache()


def start_model_setup():
    """
    Prepara os modelos Argos em um processo separado.

    A Nuvy continua iniciando normalmente.
    O Argos não fica carregado no processo principal.
    """
    import subprocess
    import threading

    def run_setup():
        print("☁️ Checking Argos translation models...")

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "setup_models.py"
                ],
                env=worker_environment(),
                text=True,
                capture_output=True
            )

            if result.stdout:
                print(result.stdout)

            if result.returncode == 0:
                print("☁️ Translation models are ready!")

            else:
                print(
                    "❌ Model setup failed:"
                )

                if result.stderr:
                    print(result.stderr)

        except Exception as error:
            print(
                f"❌ Model setup error: {error}"
            )

    thread = threading.Thread(
        target=run_setup,
        daemon=True
    )

    thread.start()


# Prepara os modelos separadamente.
start_model_setup()

# Discord inicia sem esperar o Argos.
client.run(TOKEN)
