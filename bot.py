import os
import asyncio
import discord
import argostranslate.package
import argostranslate.translate

# =========================================================
# NUVY ☁️
# Discord translator: Português ↔ English ↔ Español
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

# IDs dos canais.
# Vamos preencher depois que criarmos/confirmarmos os canais no Discord.
CHANNELS = {
    "pt": 0,
    "en": 0,
    "es": 0,
}

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# ---------------------------------------------------------
# ARGOS TRANSLATE
# ---------------------------------------------------------

def install_translation_models():
    """
    Verifica e instala os modelos gratuitos necessários.
    O inglês será usado como idioma intermediário quando necessário.
    """

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
            (lang for lang in installed_languages if lang.code == from_code),
            None
        )

        if not from_lang:
            return False

        try:
            from_lang.get_translation(
                next(
                    lang for lang in installed_languages
                    if lang.code == to_code
                )
            )
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

            # Atualiza a lista depois de instalar cada modelo
            installed_languages = (
                argostranslate.translate.get_installed_languages()
            )

            print(f"✓ Modelo {from_code} → {to_code} instalado")
        else:
            print(f"⚠️ Modelo não encontrado: {from_code} → {to_code}")


def translate_text(text, source, target):
    """Traduz uma mensagem para o idioma desejado."""

    if source == target:
        return text

    installed_languages = argostranslate.translate.get_installed_languages()

    source_language = next(
        (lang for lang in installed_languages if lang.code == source),
        None
    )

    target_language = next(
        (lang for lang in installed_languages if lang.code == target),
        None
    )

    if not source_language or not target_language:
        raise RuntimeError(
            f"Idioma não instalado: {source} → {target}"
        )

    translation = source_language.get_translation(target_language)

    return translation.translate(text)


async def get_nuvy_webhook(channel):
    """Obtém ou cria o webhook usado pela Nuvy."""

    webhooks = await channel.webhooks()

    for webhook in webhooks:
        if webhook.name == "Nuvy Translator":
            return webhook

    return await channel.create_webhook(name="Nuvy Translator")


async def send_translation(channel, message, translated_text):
    """Envia a tradução preservando nome e avatar do autor."""

    webhook = await get_nuvy_webhook(channel)

    avatar_url = message.author.display_avatar.url

    await webhook.send(
        content=translated_text,
        username=message.author.display_name,
        avatar_url=avatar_url,
        allowed_mentions=discord.AllowedMentions.none(),
        wait=True,
    )


# ---------------------------------------------------------
# DISCORD
# ---------------------------------------------------------

@client.event
async def on_ready():
    print("--------------------------------")
    print(f"☁️ Nuvy conectada como {client.user}")
    print("PT • EN • ES")
    print("--------------------------------")


@client.event
async def on_message(message):

    # Ignora bots e webhooks para evitar loops infinitos
    if message.author.bot or message.webhook_id is not None:
        return

    # Descobre em qual canal/idioma a mensagem foi enviada
    source_language = None

    for language, channel_id in CHANNELS.items():
        if message.channel.id == channel_id:
            source_language = language
            break

    # Se não for um dos canais configurados, não faz nada
    if source_language is None:
        return

    # Ignora mensagens vazias
    if not message.content.strip():
        return

    # Traduz para os outros canais
    for target_language, target_channel_id in CHANNELS.items():

        if target_language == source_language:
            continue

        if target_channel_id == 0:
            continue

        target_channel = client.get_channel(target_channel_id)

        if target_channel is None:
            continue

        try:
            translated = await asyncio.to_thread(
                translate_text,
                message.content,
                source_language,
                target_language,
            )

            await send_translation(
                target_channel,
                message,
                translated,
            )

        except Exception as error:
            print(
                f"Erro traduzindo "
                f"{source_language} → {target_language}: {error}"
            )


# ---------------------------------------------------------
# START
# ---------------------------------------------------------

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN não foi configurado."
    )

install_translation_models()

client.run(TOKEN)
