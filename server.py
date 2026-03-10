"""Backward-compatible HTTP entrypoint."""

import os

from app.api.routes import create_app

app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
