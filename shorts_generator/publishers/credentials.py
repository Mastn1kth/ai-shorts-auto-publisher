"""Optional OS credential-store integration for the local web UI."""

import os


SERVICE_NAME = "shortform-local-studio"


def get_secret(name: str) -> str:
    try:
        import keyring  # type: ignore
        saved = keyring.get_password(SERVICE_NAME, name)
        if saved:
            return saved.strip()
    except Exception:
        pass
    return os.getenv(name, "").strip()


def save_secret(name: str, value: str) -> None:
    import keyring  # type: ignore
    keyring.set_password(SERVICE_NAME, name, value.strip())
