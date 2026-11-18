"""Production entry point: python wsgi.py (Waitress WSGI server)."""

from __future__ import annotations

import os

from waitress import create_server

from app import create_app

application = create_app(os.getenv("SHADOW_ENV", "production"))


def server_options() -> dict:
    """Return the Waitress options used by both foreground and hidden runs."""
    return {
        "host": os.getenv("SHADOW_HOST", "127.0.0.1"),
        "port": int(os.getenv("SHADOW_PORT", "8000")),
        "threads": int(os.getenv("SHADOW_THREADS", "8")),
        "connection_limit": 500,
        "channel_timeout": 120,
    }


def build_server():
    """Create a Waitress server around the configured Flask application."""
    return create_server(application, **server_options())


def run_server() -> None:
    build_server().run()


if __name__ == "__main__":
    run_server()
