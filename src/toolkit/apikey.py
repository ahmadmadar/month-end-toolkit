"""Startup check for the Anthropic API key.

Only TOOLKIT_ANTHROPIC_API_KEY is read. ANTHROPIC_API_KEY is deliberately
ignored so Claude Code sessions in this repo can't bill to the toolkit's key,
and there is no fallback key.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from toolkit.errors import ToolkitError

KEY_NAME = "TOOLKIT_ANTHROPIC_API_KEY"


def load_api_key(env_path: Path) -> str:
    """Return the API key from the environment or .env. Raise if it's missing or blank."""
    load_dotenv(env_path, override=False)
    key = os.environ.get(KEY_NAME, "").strip()
    if not key:
        raise ToolkitError(
            f"No API key found. Add {KEY_NAME}=<your key> to {env_path.name} "
            f"(copy .env.example to start). ANTHROPIC_API_KEY is not used."
        )
    return key
