"""Запустить выбранные учебные CSV по порядку в новой временной базе.

Можно менять копии входа и наблюдать COMMIT/ROLLBACK, не настраивая постоянный сервер.
Отвергнутая партия сохраняется в отчёте как ошибка и даёт общий exit 1.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_ledger.core import DataError, initialize, load_batch, snapshot
from stock_ledger.lab import temporary_postgres


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Лабораторная: CSV по порядку, одна временная база")
    parser.add_argument("files", nargs="+", type=Path, help="Явный список CSV в порядке загрузки")
    parser.add_argument("--output", type=Path, default=Path("workspace/experiment"), help="Новая папка отчёта")
    parser.add_argument("--repeat-first", action="store_true", help="Повторить первую партию с тем же ключом")
    args = parser.parse_args()
    if args.output.exists():
        print("Папка отчёта уже существует; выбери другую --output.", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True)
    results = []
    rejected = False
    with temporary_postgres() as dsn:
        initialize(dsn)
        for number, source in enumerate(args.files, start=1):
            # Ключ зависит от позиции в этом опыте. Это не промышленная схема batch_id.
            key = "case-" + str(number)
            try:
                result = load_batch(dsn, key, source)
            except DataError as exc:
                result = {"batch_id": key, "rejected": str(exc)}
                rejected = True
            else:
                if number == 1 and args.repeat_first:
                    result["repeat"] = load_batch(dsn, key, source)
            results.append({"load": result, "snapshot": snapshot(dsn)})
    text = json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    (args.output / "steps.json").write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
