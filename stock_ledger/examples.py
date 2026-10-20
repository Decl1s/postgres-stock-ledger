"""Фиксированные синтетические события: только вымышленные ID и коды товаров."""

import csv
from pathlib import Path

CASES = {
    "receipts": [("E0001", "BOOK", 10), ("E0002", "PEN", 20), ("E0003", "BAG", 5), ("E0001", "BOOK", 10)],
    "dispatch": [("E0004", "BOOK", -3), ("E0005", "PEN", -4), ("E0006", "BAG", -2), ("E0002", "PEN", 20)],
    "negative": [("E0007", "BOOK", 2), ("E0008", "BAG", -99)],
    "conflict": [("E0001", "BOOK", 11)],
    "failure": [("E0009", "BOOK", 1)],
}


def write_csv(path: Path, events: list) -> None:
    """Создать новый CSV с LF и точным порядком полей; не перезаписывать чужие правки."""
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["event_id", "sku", "delta"])
        writer.writerows(events)


def generate(folder: Path) -> None:
    """Папка должна быть новой. Каждый повтор может использовать другое --output."""
    folder.mkdir(parents=True, exist_ok=False)
    for name, events in CASES.items():
        write_csv(folder / (name + ".csv"), events)
