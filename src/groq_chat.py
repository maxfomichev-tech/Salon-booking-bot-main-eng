from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from groq import Groq

SYSTEM_PROMPT_EN = """You are Aaron, the administrator of beauty salon "{salon_name}".
Salon address: {address}.
Today: {current_date}, {weekday} (timezone {timezone}).

IMPORTANT:
- If the client says "tomorrow", "day after tomorrow" — calculate from today's date.
- Do not invent dates — use today's date as a reference point.
- Working hours: {work_start}:00 to {work_end}:00, closed on Saturdays. Open Sunday through Friday.

Your task: briefly and politely consult the client about services, prices, duration, aftercare and preparation.
If the client wants to book, ask for: service, date, time, name, and phone number.
If the client says "yes", "book", "I want to book" — suggest the /book command.
Respond in English, with short messages.
Do not answer unrelated questions — only about salon services and booking. Gently steer the conversation back to the salon.

Services list:
{services_text}
"""


class GroqConsultant:
    def __init__(
        self,
        api_key: str,
        model: str,
        salon_name: str,
        services_text: str,
        address: str,
        timezone: str = "Asia/Jerusalem",
        work_start_hour: int = 10,
        work_end_hour: int = 20,
    ) -> None:
        self._client = Groq(api_key=api_key)
        self._model = model
        self._salon_name = salon_name
        self._services_text = services_text
        self._address = address
        self._timezone = timezone
        self._work_start_hour = work_start_hour
        self._work_end_hour = work_end_hour

    def _get_datetime_context(self) -> tuple[str, str]:
        now = datetime.now(ZoneInfo(self._timezone))
        current_date = now.strftime("%d.%m.%Y %H:%M")

        weekday = now.strftime("%A")

        return current_date, weekday

    def reply(self, user_text: str) -> str:
        current_date, weekday = self._get_datetime_context()

        system_prompt = SYSTEM_PROMPT_EN.format(
            salon_name=self._salon_name,
            services_text=self._services_text,
            address=self._address,
            current_date=current_date,
            weekday=weekday,
            timezone=self._timezone,
            work_start=self._work_start_hour,
            work_end=self._work_end_hour,
        )

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.1,
            max_tokens=350,
        )
        return (resp.choices[0].message.content or "").strip()
