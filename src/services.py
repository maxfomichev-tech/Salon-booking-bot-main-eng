from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Service:
    category: str
    service: str
    duration_minutes: int
    price_usd: int

    @property
    def label(self) -> str:
        return f"{self.service} — {self.duration_minutes} min — ${self.price_usd}"


def load_services(csv_path: Path) -> list[Service]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Services CSV not found: {csv_path}")

    items: list[Service] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            items.append(
                Service(
                    category=(row.get("category") or "").strip(),
                    service=(row.get("service") or "").strip(),
                    duration_minutes=int(row.get("duration_minutes") or 0),
                    price_usd=int(row.get("price_usd") or 0),
                )
            )
    if not items:
        raise RuntimeError(f"Services CSV is empty: {csv_path}")
    return items


def format_services(services: Iterable[Service], limit: int = 30) -> str:
    lines: list[str] = []
    count = 0
    for s in services:
        lines.append(f"- {s.category}: {s.label}")
        count += 1
        if count >= limit:
            break
    if not lines:
        return "Price list is empty."
    return "📋 Here are our services:\n" + "\n".join(lines)
