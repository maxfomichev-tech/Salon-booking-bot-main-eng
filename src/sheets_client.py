from __future__ import annotations

import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import Optional


class SheetsClient:
    def __init__(self, spreadsheet_id: str, credentials_json: str) -> None:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(
            json.loads(credentials_json), scopes=scopes
        )
        self._client = gspread.authorize(creds)
        self._sheet = self._client.open_by_key(spreadsheet_id).sheet1

    @staticmethod
    def _is_meaningful_identity_value(value: str) -> bool:
        """
        Защита от затирания имени/телефона мусорными значениями.
        """
        v = (value or "").strip()
        if not v:
            return False

        lowered = v.lower()
        placeholders = {
            "-",
            "—",
            "нет",
            "не знаю",
            "не помню",
            "аноним",
            "unknown",
            "n/a",
            "na",
            "none",
            "don't know",
            "don't remember",
            "anonymous",
        }
        return lowered not in placeholders

    @staticmethod
    def _as_plain_text(value: object) -> str:
        """
        Google Sheets может трактовать значения, начинающиеся с '+', '-', '=' как формулы.
        Принудительно сохраняем как текст (через апостроф).
        """
        s = "" if value is None else str(value)
        if s.startswith("'"):
            return s
        if s.startswith(("+", "-", "=")):
            return "'" + s
        return s

    def add_or_update(
        self,
        client_id: str,
        name: str,
        phone: str,
        service_name: str,
        service_dt_iso: str | None = None,
    ) -> None:
        """Добавляет нового клиента или обновляет существующего."""
        now = datetime.now().isoformat()
        service_dt = service_dt_iso or now

        # gspread exception names differ between versions; resolve dynamically.
        cell_not_found_exc = getattr(getattr(gspread, "exceptions", object()), "CellNotFound", None)

        # Ищем клиента по ID
        try:
            cell = self._sheet.find(client_id)
            if cell is None:
                raise LookupError(f"Client id not found: {client_id}")
            row = cell.row
            
            # Обновляем существующего
            # RAW + экранирование, чтобы '+' в телефоне не воспринимался формулой
            self._sheet.update(
                f"E{row}:G{row}",
                [[
                    self._as_plain_text(now),
                    self._as_plain_text(service_dt),
                    self._as_plain_text(service_name),
                ]],
                value_input_option="USER_ENTERED",
            )
            current_visits = int(self._sheet.cell(row, 8).value or 0)
            self._sheet.update(
                f"H{row}:H{row}",
                [[current_visits + 1]],
                value_input_option="RAW",
            )

            # Имя/телефон обновляем только если пришли осмысленные значения,
            # чтобы не затирать существующие данные пустыми/мусорными ответами.
            existing = self._sheet.row_values(row)
            existing_name = (existing[1] if len(existing) > 1 else "").strip()
            existing_phone = (existing[2] if len(existing) > 2 else "").strip()

            name_to_write = name.strip() if self._is_meaningful_identity_value(name) else ""
            phone_to_write = phone.strip() if self._is_meaningful_identity_value(phone) else ""

            should_update_name = bool(name_to_write) and name_to_write != existing_name
            should_update_phone = bool(phone_to_write) and phone_to_write != existing_phone

            if should_update_name or should_update_phone:
                final_name = name_to_write if should_update_name else existing_name
                final_phone = phone_to_write if should_update_phone else existing_phone
                self._sheet.update(
                    f"B{row}:C{row}",
                    [[
                        self._as_plain_text(final_name),
                        self._as_plain_text(final_phone),
                    ]],
                    value_input_option="USER_ENTERED",
                )
        except Exception as e:
            if isinstance(e, LookupError) or (
                cell_not_found_exc is not None and isinstance(e, cell_not_found_exc)
            ):
                # Новый клиент
                self._sheet.append_row(
                    [
                        self._as_plain_text(client_id),
                        self._as_plain_text(name),
                        self._as_plain_text(phone),
                        self._as_plain_text(now),  # first_contact
                        self._as_plain_text(now),  # last_contact
                        self._as_plain_text(service_dt),  # last_service_date
                        self._as_plain_text(service_name),
                        1,  # total_visits
                    ],
                    value_input_option="USER_ENTERED",
                )
                return
            raise

    def get_client(self, client_id: str) -> Optional[dict]:
        cell_not_found_exc = getattr(getattr(gspread, "exceptions", object()), "CellNotFound", None)
        try:
            cell = self._sheet.find(client_id)
            if cell is None:
                raise LookupError(f"Client id not found: {client_id}")
            row = cell.row
            values = self._sheet.row_values(row)
            return {
                "client_id": values[0],
                "name": values[1],
                "phone": values[2],
                "first_contact": values[3],
                "last_contact": values[4],
                "last_service_date": values[5],
                "last_service_name": values[6],
                "total_visits": values[7],
            }
        except Exception as e:
            if isinstance(e, LookupError) or (
                cell_not_found_exc is not None and isinstance(e, cell_not_found_exc)
            ):
                return None
            raise