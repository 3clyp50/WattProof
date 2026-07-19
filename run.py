from __future__ import annotations

import os

from wattproof.app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("WATTPROOF_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
