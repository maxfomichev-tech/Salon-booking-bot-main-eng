from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os
import json


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    groq_api_key: str
    groq_model: str
    services_csv: Path
    google_calendar_id: str
    google_service_account_json_path: Path | None
    google_service_account_json_content: str | None
    salon_timezone: str
    salon_name: str
    address: str
    google_sheets_id: str
    work_start_hour: int
    work_end_hour: int


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def load_config() -> Config:
    load_dotenv()

    services_csv = Path(os.getenv("SERVICES_CSV", "services_pricelist.csv"))
    sa_content = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")
    sa_path_raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

    # Common deployment setups put the JSON content directly into
    # GOOGLE_SERVICE_ACCOUNT_JSON (despite the name). Detect that.
    if (not sa_content) and sa_path_raw:
        v = sa_path_raw.strip()
        if v.startswith("{") and v.endswith("}"):
            sa_content = v
            sa_path_raw = None

    if sa_content:
        # Validate JSON early for clearer errors
        json.loads(sa_content)

    if not sa_content and not sa_path_raw:
        raise RuntimeError(
            "Missing Google service account credentials. Set either "
            "GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT (JSON string) or GOOGLE_SERVICE_ACCOUNT_JSON (path)."
        )

    if sa_path_raw:
        p = Path(sa_path_raw)
        if not p.exists():
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is set to a file path, but the file does not exist: "
                f"{p}"
            )

    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        groq_api_key=_require("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        services_csv=services_csv,
        google_calendar_id=_require("GOOGLE_CALENDAR_ID"),
        google_service_account_json_path=Path(sa_path_raw) if sa_path_raw else None,
        google_service_account_json_content=sa_content if sa_content else None,
        salon_timezone=os.getenv("SALON_TIMEZONE", "Asia/Jerusalem"),
        salon_name=os.getenv("SALON_NAME", "Aaron"),
        address=os.getenv("ADDRESS", ""),
        google_sheets_id=os.getenv("GOOGLE_SHEETS_ID", ""),
        work_start_hour=int(os.getenv("WORK_START_HOUR", "10")),
        work_end_hour=int(os.getenv("WORK_END_HOUR", "20")),
    )

