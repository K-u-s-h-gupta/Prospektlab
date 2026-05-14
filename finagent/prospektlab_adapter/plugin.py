"""Register FinAgent behaviors with a host application (implement per deployment)."""


def register_plugin(app: object) -> None:
    """Mount routes or background workers on *app*."""
    raise NotImplementedError("Implement for your ProspektLab host process")
