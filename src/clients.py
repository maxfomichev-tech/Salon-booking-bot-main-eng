from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class ClientsManager:
    def __init__(self, csv_path: str = "clients.csv") -> None:
        self._csv_path = Path(csv_path)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        """Создаёт CSV с заголовками, если файла нет."""
        if not self._csv_path.exists():
            with self._csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "client_id", "name", "phone",
                    "first_contact", "last_contact",
                    "last_service_date", "last_service_name", "total_visits"
                ])

    def _read_all(self) -> list[dict]:
        """Читает все записи из CSV."""
        if not self._csv_path.exists():
            return []
        with self._csv_path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def _write_all(self, rows: list[dict]) -> None:
        """Перезаписывает весь CSV."""
        with self._csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "client_id", "name", "phone",
                "first_contact", "last_contact",
                "last_service_date", "last_service_name", "total_visits"
            ])
            writer.writeheader()
            writer.writerows(rows)

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
        rows = self._read_all()
        
        # Ищем по client_id
        for row in rows:
            if row["client_id"] == str(client_id):
                # Обновляем существующего
                row["last_contact"] = now
                row["last_service_date"] = service_dt
                row["last_service_name"] = service_name
                row["total_visits"] = str(int(row.get("total_visits", "0")) + 1)
                # Имя/телефон должны отражать актуальные данные клиента
                row["name"] = name
                row["phone"] = phone
                self._write_all(rows)
                return
        
        # Новый клиент
        rows.append({
            "client_id": str(client_id),
            "name": name,
            "phone": phone,
            "first_contact": now,
            "last_contact": now,
            "last_service_date": service_dt,
            "last_service_name": service_name,
            "total_visits": "1",
        })
        self._write_all(rows)

    def get_client(self, client_id: str) -> Optional[dict]:
        """Получает данные клиента по ID."""
        rows = self._read_all()
        for row in rows:
            if row["client_id"] == str(client_id):
                return row
        return None