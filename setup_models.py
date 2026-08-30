import os
import time

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


import argostranslate.package


REQUIRED_MODELS = [
    ("pt", "en"),
    ("en", "pt"),
    ("es", "en"),
    ("en", "es"),
]


def installed_pairs():
    packages = (
        argostranslate.package
        .get_installed_packages()
    )

    return {
        (
            package.from_code,
            package.to_code
        )
        for package in packages
    }


def refresh_index():
    last_error = None

    for attempt in range(1, 4):
        try:
            print(
                f"☁️ Updating Argos package index "
                f"(attempt {attempt}/3)..."
            )

            argostranslate.package.update_package_index()

            packages = (
                argostranslate.package
                .get_available_packages()
            )

            if packages:
                return packages

            last_error = RuntimeError(
                "Argos returned an empty package index."
            )

        except Exception as error:
            last_error = error

            print(
                f"⚠️ Attempt {attempt} failed: "
                f"{error}"
            )

        time.sleep(3)

    raise RuntimeError(
        "Could not load Argos package index: "
        f"{last_error}"
    )


def main():
    os.makedirs(
        os.environ["ARGOS_PACKAGES_DIR"],
        exist_ok=True
    )

    installed = installed_pairs()

    print(
        f"☁️ Installed models: "
        f"{sorted(installed)}"
    )

    missing = [
        pair
        for pair in REQUIRED_MODELS
        if pair not in installed
    ]

    if not missing:
        print(
            "✓ All required Argos models "
            "already exist."
        )
        return

    print(
        f"☁️ Missing models: {missing}"
    )

    available = refresh_index()

    for source, target in missing:
        package = next(
            (
                item
                for item in available
                if (
                    item.from_code == source
                    and item.to_code == target
                )
            ),
            None
        )

        if package is None:
            raise RuntimeError(
                f"Model unavailable: "
                f"{source} → {target}"
            )

        print(
            f"☁️ Downloading "
            f"{source} → {target}..."
        )

        path = package.download()

        argostranslate.package.install_from_path(
            path
        )

        print(
            f"✓ Installed "
            f"{source} → {target}"
        )

    print(
        "☁️ All translation models ready."
    )


if __name__ == "__main__":
    main()
