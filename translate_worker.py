import os
import sys
import json


# Configuração ANTES de importar Argos.
os.environ.setdefault(
    "ARGOS_PACKAGES_DIR",
    "/data/argos-packages"
)

os.environ.setdefault(
    "ARGOS_DEVICE_TYPE",
    "cpu"
)

os.environ.setdefault(
    "ARGOS_INTER_THREADS",
    "1"
)

os.environ.setdefault(
    "ARGOS_INTRA_THREADS",
    "1"
)

os.environ.setdefault(
    "ARGOS_BATCH_SIZE",
    "1"
)


import argostranslate.translate


def translate(text, source, target):
    return argostranslate.translate.translate(
        text,
        source,
        target
    )


def main():
    try:
        raw = sys.stdin.buffer.read()

        if not raw:
            raise RuntimeError(
                "Worker received no translation request."
            )

        request = json.loads(
            raw.decode("utf-8")
        )

        text = request.get("text", "")
        source = request.get("source")

        if not text.strip():
            raise RuntimeError(
                "Translation text is empty."
            )

        result = {}

        # PORTUGUÊS
        if source == "pt":
            english = translate(
                text,
                "pt",
                "en"
            )

            spanish = translate(
                english,
                "en",
                "es"
            )

            result["en"] = english
            result["es"] = spanish

        # INGLÊS
        elif source == "en":
            portuguese = translate(
                text,
                "en",
                "pt"
            )

            spanish = translate(
                text,
                "en",
                "es"
            )

            result["pt"] = portuguese
            result["es"] = spanish

        # ESPANHOL
        elif source == "es":
            english = translate(
                text,
                "es",
                "en"
            )

            portuguese = translate(
                english,
                "en",
                "pt"
            )

            result["en"] = english
            result["pt"] = portuguese

        else:
            raise RuntimeError(
                f"Unsupported source language: "
                f"{source}"
            )

        # IMPORTANTE:
        # stdout contém SOMENTE JSON.
        sys.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False
            )
        )

        sys.stdout.flush()

    except Exception as error:
        sys.stdout.write(
            json.dumps(
                {
                    "error": str(error)
                },
                ensure_ascii=False
            )
        )

        sys.stdout.flush()


if __name__ == "__main__":
    main()
