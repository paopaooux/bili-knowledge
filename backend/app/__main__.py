import os

import uvicorn

from .config import load_settings

if __name__ == "__main__":
    # Load config.env before reading the bind address. Keep loopback as the safe default;
    # LAN/mobile access must be opted into explicitly with BACKEND_HOST=0.0.0.0.
    load_settings()
    uvicorn.run(
        "app.main:app",
        host=os.getenv("BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=False,
    )
