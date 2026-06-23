from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import uuid

from google.oauth2 import service_account
from googleapiclient.discovery import build


@dataclass(frozen=True)
class Booking:
    service_name: str
    client_name: str
    phone: str
    start: datetime
    duration_minutes: int
    timezone: str
    salon_name: str

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)


class GoogleCalendarClient:
    def __init__(
        self,
        calendar_id: str,
        *,
        service_account_json_path: str | None = None,
        service_account_json_content: str | None = None,
    ) -> None:
        if service_account_json_content:
            info = json.loads(service_account_json_content)
            creds = service_account.Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
        elif service_account_json_path:
            creds = service_account.Credentials.from_service_account_file(
                service_account_json_path,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
        else:
            raise ValueError(
                "Provide service_account_json_content or service_account_json_path"
            )

        self._service = build(
            "calendar", "v3", credentials=creds, cache_discovery=False
        )
        self._calendar_id = calendar_id

    def is_time_available(self, start: datetime, end: datetime) -> bool:
        """Проверяет, свободно ли время в календаре."""
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": self._calendar_id}],
        }
        result = self._service.freebusy().query(body=body).execute()
        busy_times = result["calendars"][self._calendar_id]["busy"]
        return len(busy_times) == 0

    def create_booking_event(self, booking: Booking) -> str:
        summary = f"{booking.salon_name}: {booking.service_name}"
        description = f"👤 Client: {booking.client_name}\n📞 Phone: {booking.phone}\n✂️ Service: {booking.service_name}\n🏠 Salon: {booking.salon_name}"
        body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": booking.start.isoformat(),
                "timeZone": booking.timezone,
            },
            "end": {"dateTime": booking.end.isoformat(), "timeZone": booking.timezone},
        }
        event = (
            self._service.events()
            .insert(calendarId=self._calendar_id, body=body)
            .execute()
        )
        return event.get("htmlLink") or ""

    def generate_ics(self, booking: Booking) -> str:
        """Генерирует .ics файл для клиента."""
        uid = str(uuid.uuid4())
        dt_format = "%Y%m%dT%H%M%S"
        start_str = booking.start.strftime(dt_format)
        end_str = booking.end.strftime(dt_format)

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:-//{booking.salon_name}//RU",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}@salon-bot",
            f"DTSTART;TZID={booking.timezone}:{start_str}",
            f"DTEND;TZID={booking.timezone}:{end_str}",
            f"SUMMARY:{booking.service_name} — {booking.salon_name}",
            f"DESCRIPTION:👤 Client: {booking.client_name}\\n📞 Phone: {booking.phone}\\n✂️ Service: {booking.service_name}\\n🏠 Salon: {booking.salon_name}",
            f"LOCATION:{booking.salon_name}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]

        return "\r\n".join(lines)
