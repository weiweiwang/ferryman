from __future__ import annotations

_registered = False


def register_rpc_methods() -> None:
    global _registered
    if _registered:
        return

    import app.rpc.agent_runs  # noqa: F401
    import app.rpc.browser  # noqa: F401
    import app.rpc.logs  # noqa: F401
    import app.rpc.schedules  # noqa: F401
    import app.rpc.sessions  # noqa: F401
    import app.rpc.settings  # noqa: F401
    import app.rpc.skills  # noqa: F401
    import app.rpc.system  # noqa: F401
    import app.rpc.tasks  # noqa: F401

    _registered = True

