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
# CACHES
# =========================================================

# (guild_id, channel_id) -> informações do grupo
group_cache = {}

# channel_id -> webhook
webhook_cache = {}

# ("pt", "en") -> tradutor carregado
translator_cache = {}


# =========================================================
# BANCO DE DADOS
# =========================================================

def init_db():

    conn = sqlite3.connect(DB_PATH)

    # Tabela dos grupos
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

    # -----------------------------------------------------
    # MIGRAÇÃO:
    # adiciona a coluna "name" caso o banco seja antigo
    # -----------------------------------------------------

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(translation_groups)"
        ).fetchall()
    }

    if "name" not in columns:

        conn.execute(
            """
            ALTER TABLE translation_groups
            ADD COLUMN name TEXT
            """
        )

    # Grupos antigos recebem nome automático
    conn.execute(
        """
        UPDATE translation_groups
        SET name = 'Group ' || id
        WHERE name IS NULL
        OR TRIM(name) = ''
        """
    )

    # Evita dois grupos com mesmo nome no mesmo servidor
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_translation_group_name
        ON translation_groups(
            guild_id,
            name COLLATE NOCASE
        )
        """
    )

    # Relação entre mensagens PT / EN / ES
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


# =========================================================
# CACHE DOS GRUPOS
# =========================================================

def load_group_cache():

    global group_cache

    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute(
        """
        SELECT
            id,
            guild_id,
            name,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        """
    ).fetchall()

    conn.close()

    group_cache = {}

    for (
        group_id,
        guild_id,
        name,
        pt_id,
        en_id,
        es_id
    ) in rows:

        group_data = {
            "id": group_id,
            "name": name,
            "pt": pt_id,
            "en": en_id,
            "es": es_id,
        }

        group_cache[(guild_id, pt_id)] = group_data
        group_cache[(guild_id, en_id)] = group_data
        group_cache[(guild_id, es_id)] = group_data

    print(
        f"☁️ Translation groups loaded: "
        f"{len(rows)}"
    )


# =========================================================
# FUNÇÕES DOS GRUPOS
# =========================================================

def get_groups(guild_id):

    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute(
        """
        SELECT
            id,
            name,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        FROM translation_groups
        WHERE guild_id = ?
        ORDER BY name COLLATE NOCASE
        """,
        (guild_id,)
    ).fetchall()

    conn.close()

    return rows


def group_name_exists(guild_id, name):

    conn = sqlite3.connect(DB_PATH)

    row = conn.execute(
        """
        SELECT id
        FROM translation_groups
        WHERE guild_id = ?
        AND name = ? COLLATE NOCASE
        LIMIT 1
        """,
        (
            guild_id,
            name.strip()
        )
    ).fetchone()

    conn.close()

    return row is not None


def add_group(
    guild_id,
    name,
    pt_id,
    en_id,
    es_id
):

    clean_name = name.strip()

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
        """
        INSERT INTO translation_groups (
            guild_id,
            name,
            pt_channel_id,
            en_channel_id,
            es_channel_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            clean_name,
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


def delete_group_by_name(
    guild_id,
    group_name
):

    conn = sqlite3.connect(DB_PATH)

    row = conn.execute(
        """
        SELECT id, name
        FROM translation_groups
        WHERE guild_id = ?
        AND name = ? COLLATE NOCASE
        LIMIT 1
        """,
        (
            guild_id,
            group_name.strip()
        )
    ).fetchone()

    if row is None:

        conn.close()

        return None

    group_id, actual_name = row

    # Limpa vínculos de mensagens desse grupo
    conn.execute(
        """
        DELETE FROM message_links
        WHERE guild_id = ?
        AND group_id = ?
        """,
        (
            guild_id,
            group_id
        )
    )

    # Remove o grupo
    conn.execute(
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
    conn.close()

    load_group_cache()

    return actual_name


# =========================================================
# VÍNCULO ENTRE MENSAGENS
# =========================================================

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


def get_message_link(
    guild_id,
    message_id
):

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

    (
        group_id,
        pt_id,
        en_id,
        es_id
    ) = row

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

    print(
        "☁️ Checking translation models..."
    )

    argostranslate.package.update_package_index()

    available_packages = (
        argostranslate.package
        .get_available_packages()
    )

    installed_packages = (
        argostranslate.package
        .get_installed_packages()
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

    # Modelos obrigatórios
    for source, target in required_pairs:

        if is_installed(
            source,
            target
        ):

            print(
                f"✓ Model installed: "
                f"{source} → {target}"
            )

            continue

        package = next(
            (
                p
                for p in available_packages
                if p.from_code == source
                and p.to_code == target
            ),
            None
        )

        if package is None:

            raise RuntimeError(
                f"Required model not found: "
                f"{source} → {target}"
            )

        print(
            f"☁️ Installing model: "
            f"{source} → {target}"
        )

        download_path = (
            package.download()
        )

        argostranslate.package.install_from_path(
            download_path
        )

        installed_packages = (
            argostranslate.package
            .get_installed_packages()
        )

    # Modelos diretos opcionais PT ↔ ES
    optional_pairs = [
        ("pt", "es"),
        ("es", "pt"),
    ]

    for source, target in optional_pairs:

        if is_installed(
            source,
            target
        ):
            continue

        package = next(
            (
                p
                for p in available_packages
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

            download_path = (
                package.download()
            )

            argostranslate.package.install_from_path(
                download_path
            )

            installed_packages = (
                argostranslate.package
                .get_installed_packages()
            )

        except Exception as error:

            print(
                f"⚠️ Optional model skipped: "
                f"{error}"
            )


# =========================================================
# CACHE DOS TRADUTORES
# =========================================================

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
        ("es", "en"),
        ("en", "es"),
        ("pt", "es"),
        ("es", "pt"),
    ]

    for source, target in pairs:

        source_language = (
            language_map.get(source)
        )

        target_language = (
            language_map.get(target)
        )

        if (
            not source_language
            or not target_language
        ):
            continue

        try:

            translation = (
                source_language
                .get_translation(
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


def translate_direct(
    text,
    source,
    target
):

    translator = (
        translator_cache.get(
            (source, target)
        )
    )

    if translator is None:

        raise RuntimeError(
            f"Translator unavailable: "
            f"{source} → {target}"
        )

    return translator.translate(text)


@lru_cache(maxsize=3000)
def translate_cached(
    text,
    source,
    target
):

    if source == target:
        return text

    direct = translator_cache.get(
        (source, target)
    )

    if direct is not None:

        return direct.translate(text)

    # Português → Espanhol via Inglês
    if (
        source == "pt"
        and target == "es"
    ):

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

    # Espanhol → Português via Inglês
    if (
        source == "es"
        and target == "pt"
    ):

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

    cached = webhook_cache.get(
        channel.id
    )

    if cached is not None:
        return cached

    webhooks = (
        await channel.webhooks()
    )

    for webhook in webhooks:

        if (
            webhook.name
            == "Nuvy Translator"
        ):

            webhook_cache[
                channel.id
            ] = webhook

            return webhook

    webhook = (
        await channel.create_webhook(
            name="Nuvy Translator"
        )
    )

    webhook_cache[
        channel.id
    ] = webhook

    return webhook


async def warm_webhook(channel):

    try:

        await get_nuvy_webhook(
            channel
        )

    except Exception as error:

        print(
            f"⚠️ Webhook error "
            f"in #{channel.name}: "
            f"{error}"
        )


async def prepare_group_webhooks(
    portugues,
    english,
    espanhol
):

    try:

        await asyncio.gather(
            warm_webhook(portugues),
            warm_webhook(english),
            warm_webhook(espanol)
        )

        print(
            "✓ Translation group "
            "webhooks prepared."
        )

    except Exception as error:

        print(
            f"⚠️ Error preparing "
            f"webhooks: {error}"
        )


# =========================================================
# REPLIES
# =========================================================

async def get_reply_information(
    original_message,
    target_language,
    target_channel
):

    if (
        original_message.reference
        is None
    ):
        return None

    referenced_id = (
        original_message
        .reference
        .message_id
    )

    if referenced_id is None:
        return None

    link = get_message_link(
        original_message.guild.id,
        referenced_id
    )

    if link is None:
        return None

    target_message_id = (
        link.get(
            target_language
        )
    )

    if target_message_id is None:
        return None

    try:

        return (
            await target_channel
            .fetch_message(
                target_message_id
            )
        )

    except Exception:
        return None


async def send_translation(
    target_channel,
    original_message,
    translated_text,
    target_language
):

    webhook = (
        await get_nuvy_webhook(
            target_channel
        )
    )

    replied_message = (
        await get_reply_information(
            original_message,
            target_language,
            target_channel
        )
    )

    # -----------------------------------------------------
    # Se for reply, mostra a mensagem correspondente
    # traduzida no canal de destino
    # -----------------------------------------------------

    if replied_message is not None:

        reply_author = (
            replied_message
            .author
            .display_name
        )

        reply_preview = (
            replied_message.content.strip()
            if replied_message.content
            else "message"
        )

        if len(reply_preview) > 120:

            reply_preview = (
                reply_preview[:120]
                + "…"
            )

        translated_text = (
            f"↪️ **{reply_author}:** "
            f"{reply_preview}\n"
            f"{translated_text}"
        )

    sent_message = await webhook.send(
        content=translated_text,
        username=(
            original_message
            .author
            .display_name
        ),
        avatar_url=(
            original_message
            .author
            .display_avatar
            .url
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
        interaction.guild
        is not None
        and interaction.guild.id
        in ALLOWED_GUILDS
    )


def can_manage_translation(
    interaction
):

    if interaction.guild is None:
        return False

    permissions = (
        interaction.user
        .guild_permissions
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
# AUTOCOMPLETE DOS GRUPOS
# =========================================================

async def group_autocomplete(
    interaction: discord.Interaction,
    current: str
):

    if (
        interaction.guild is None
        or interaction.guild.id
        not in ALLOWED_GUILDS
    ):
        return []

    groups = get_groups(
        interaction.guild.id
    )

    current_lower = (
        current.lower().strip()
    )

    choices = []

    for (
        _group_id,
        name,
        _pt,
        _en,
        _es
    ) in groups:

        if (
            not current_lower
            or current_lower
            in name.lower()
        ):

            choices.append(
                app_commands.Choice(
                    name=name,
                    value=name
                )
            )

    # Discord permite no máximo 25
    return choices[:25]


# =========================================================
# /LINK
# =========================================================

@tree.command(
    name="link",
    description=(
        "Create a translation group."
    )
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

    # Servidor permitido?
    if not guild_allowed(interaction):

        await reject_unauthorized_guild(
            interaction
        )

        return

    # Permissão para configurar?
    if not can_manage_translation(
        interaction
    ):

        await interaction.response.send_message(
            (
                "☁️ You need Manage Server "
                "permission to use this command."
            ),
            ephemeral=True
        )

        return

    clean_name = nome.strip()

    # Nome vazio ou exageradamente curto
    if len(clean_name) < 2:

        await interaction.response.send_message(
            (
                "☁️ Please choose a name "
                "for this translation group."
            ),
            ephemeral=True
        )

        return

    if len(clean_name) > 40:

        await interaction.response.send_message(
            (
                "☁️ Group names can have "
                "up to 40 characters."
            ),
            ephemeral=True
        )

        return

    # Nome já existe?
    if group_name_exists(
        interaction.guild.id,
        clean_name
    ):

        await interaction.response.send_message(
            (
                f"☁️ A translation group "
                f"named **{clean_name}** "
                f"already exists."
            ),
            ephemeral=True
        )

        return

    selected_ids = {
        portugues.id,
        english.id,
        espanhol.id
    }

    # Canais precisam ser diferentes
    if len(selected_ids) != 3:

        await interaction.response.send_message(
            (
                "☁️ Please select three "
                "different channels."
            ),
            ephemeral=True
        )

        return

    # Um canal não pode pertencer
    # a dois grupos diferentes
    for channel_id in selected_ids:

        if (
            interaction.guild.id,
            channel_id
        ) in group_cache:

            existing_group = (
                group_cache[
                    (
                        interaction.guild.id,
                        channel_id
                    )
                ]
            )

            await interaction.response.send_message(
                (
                    "☁️ One of these channels "
                    "already belongs to "
                    f"**{existing_group['name']}**."
                ),
                ephemeral=True
            )

            return

    # Salva o grupo
    group_id = add_group(
        interaction.guild.id,
        clean_name,
        portugues.id,
        english.id,
        espanhol.id
    )

    # -----------------------------------------------------
    # IMPORTANTE:
    # responde imediatamente.
    # Não espera os webhooks.
    # Corrige o "Nuvy está pensando..."
    # -----------------------------------------------------

    await interaction.response.send_message(
        (
            f"☁️ **{clean_name} connected!**\n\n"
            f"🇧🇷 {portugues.mention}\n"
            f"🇺🇸 {english.mention}\n"
            f"🇪🇸 {espanhol.mention}\n\n"
            f"Group ID: `{group_id}`"
        )
    )

    # Webhooks preparados em segundo plano
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
        _group_id,
        name,
        pt_id,
        en_id,
        es_id
    ) in groups_list:

        blocks.append(
            (
                f"### ☁️ {name}\n"
                f"🇧🇷 <#{pt_id}>\n"
                f"🇺🇸 <#{en_id}>\n"
                f"🇪🇸 <#{es_id}>"
            )
        )

    await interaction.response.send_message(
        (
            "## ☁️ Nuvy Translation Groups\n\n"
            + "\n\n".join(blocks)
        )
    )


# =========================================================
# /UNLINK
# =========================================================

@tree.command(
    name="unlink",
    description=(
        "Remove a translation group."
    )
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

        await reject_unauthorized_guild(
            interaction
        )

        return

    if not can_manage_translation(
        interaction
    ):

        await interaction.response.send_message(
            (
                "☁️ You need Manage Server "
                "permission to use this command."
            ),
            ephemeral=True
        )

        return

    removed_name = delete_group_by_name(
        interaction.guild.id,
        grupo
    )

    if removed_name is None:

        await interaction.response.send_message(
            (
                f"☁️ I couldn't find a group "
                f"named **{grupo}**."
            ),
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        (
            f"☁️ Translation group "
            f"**{removed_name}** removed."
        )
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
# TRADUZIR PARA UM CANAL
# =========================================================

async def process_target(
    original_message,
    source_language,
    target_language,
    target_channel_id
):

    target_channel = (
        client.get_channel(
            target_channel_id
        )
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

        sent_message = (
            await send_translation(
                target_channel,
                original_message,
                translated,
                target_language
            )
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
# RECEBER MENSAGENS
# =========================================================

@client.event
async def on_message(message):

    # Ignora bots
    if message.author.bot:
        return

    # Ignora mensagens criadas
    # pelos próprios webhooks
    if message.webhook_id is not None:
        return

    # Ignora DM
    if message.guild is None:
        return

    # Ignora servidor não autorizado
    if (
        message.guild.id
        not in ALLOWED_GUILDS
    ):
        return

    # Por enquanto precisa ter texto
    if not message.content.strip():
        return

    group = group_cache.get(
        (
            message.guild.id,
            message.channel.id
        )
    )

    # Canal não pertence a grupo algum
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

    # ID da mensagem original
    message_ids[
        source_language
    ] = message.id

    tasks = []

    # Traduz simultaneamente
    # para os outros dois idiomas
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

    # Guarda o vínculo entre
    # as três versões da mensagem
    save_message_link(
        guild_id=message.guild.id,
        group_id=group["id"],
        pt_message_id=(
            message_ids["pt"]
        ),
        en_message_id=(
            message_ids["en"]
        ),
        es_message_id=(
            message_ids["es"]
        )
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
            f"☁️ Nuvy left "
            f"unauthorized server: "
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

    groups_count = (
        len(
            {
                group["id"]
                for group
                in group_cache.values()
            }
        )
    )

    print("")
    print("================================")
    print("☁️ NUVY ONLINE")
    print(f"Logged in as: {client.user}")
    print("Languages: PT-BR • EN • ES")
    print("Replies: enabled")
    print("Allowed servers: 3")
    print(
        f"Translation groups: "
        f"{groups_count}"
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
