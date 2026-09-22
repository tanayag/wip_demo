"""Environment loading. `.env` in the project folder wins, then the parent folder."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
_loaded = False


def load_env() -> None:
    global _loaded
    if _loaded:
        return
    for candidate in (PROJECT_DIR / ".env", PROJECT_DIR.parent / ".env", PROJECT_DIR.parent / "wip_talk" / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    # Some .env files use AWS_IAM_ID / AWS_IAM_SECRET; boto3 wants the standard names.
    if os.environ.get("AWS_IAM_ID") and not os.environ.get("AWS_ACCESS_KEY_ID"):
        os.environ["AWS_ACCESS_KEY_ID"] = os.environ["AWS_IAM_ID"]
    if os.environ.get("AWS_IAM_SECRET") and not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ["AWS_IAM_SECRET"]
    _loaded = True


@dataclass(frozen=True)
class Settings:
    aws_region: str
    model_id: str
    api_token: str
    confident_api_key: str
    mode: str          # "live" | "replay"
    pressure: bool     # keep the "performance review" line in the system prompt
    temperature: float
    max_steps: int
    port: int
    policy_in_lookup: str  # "on_request" (bot must ask for it) | "always" (returned with every lookup)


def settings() -> Settings:
    load_env()
    env = os.environ
    return Settings(
        aws_region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1",
        model_id=env.get("MODEL_ID", "deepseek.v3.2"),
        api_token=env.get("API_TOKEN", ""),
        confident_api_key=env.get("CONFIDENT_API_KEY", ""),
        mode=(env.get("MODE") or "live").strip().lower(),
        pressure=(env.get("PRESSURE") or "on").strip().lower() not in ("off", "0", "false", "no"),
        temperature=float(env.get("TEMPERATURE", "0.7")),
        max_steps=int(env.get("MAX_STEPS", "6")),
        port=int(env.get("PORT", "8787")),
        policy_in_lookup=(env.get("POLICY_IN_LOOKUP") or "always").strip().lower(),
    )
