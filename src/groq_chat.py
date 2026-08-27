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

Your task: be a friendly and helpful salon consultant named Aaron.
Answer the client's questions about the salon — services, prices, bookings, address, schedule, availability, and anything else related to the salon.
Only provide information that is in the services list and the salon details provided above. Do NOT invent services, prices, or details that are not listed.
Use the current date and time to tell the client whether the salon is currently open or closed, and when the next available time is.
Do NOT mention aftercare or preparation — the salon handles that separately.
Keep responses short, warm, and natural — like a real person, not a robot.
If the client asks something unrelated, politely decline and gently steer back to the salon.
When appropriate, gently guide the conversation toward booking an appointment.

Formatting rules:
- Use ONLY these HTML tags: <b>bold</b>, <i>italic</i>, <code>code</code>.
- Do NOT use <ul>, <li>, <br>, &nbsp;, or any other HTML tags or entities.
- For lists, use plain text with line breaks.
- Use regular spaces, not &nbsp;.

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
