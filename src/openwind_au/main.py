"""Command line entry point for OpenWind-AU."""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Run the FastAPI development server."""

    uvicorn.run("openwind_au.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
