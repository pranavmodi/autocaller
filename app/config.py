import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


def _load_dotenv_variants() -> None:
    """
    Load environment variables from .env (standard) and .en (user-provided) if present.
    .env loads first, then .en can override if both exist.
    """
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    en_path = project_root / ".en"
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
    if en_path.exists():
        load_dotenv(dotenv_path=str(en_path), override=True)


_load_dotenv_variants()


@dataclass
class Settings:
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str
    openai_api_key: str
    public_base_url: str = ""


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_settings() -> Settings:
    return Settings(
        twilio_account_sid=_get_env("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_get_env("TWILIO_AUTH_TOKEN"),
        twilio_from_number=_get_env("TWILIO_FROM_NUMBER"),
        openai_api_key=_get_env("OPENAI_API_KEY"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "") or "",
    )


