"""Register FinAgent behaviors with a host application (implement per deployment)."""


def register_plugin(app: object) -> None:
    """No-op plugin hook.

    This adapter is intentionally safe to import in environments where no host
    integration is configured yet.
    """
    return None
