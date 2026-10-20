"""CLI: демо само управляет сервером; init/load/report используют явный STOCK_DSN."""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from .core import DataError, DemoFailure, initialize, load_batch, snapshot
from .examples import generate
from .lab import temporary_postgres


def json_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def demo(folder: Path) -> dict:
    """Показать COMMIT, повтор и три ROLLBACK; база удалится, отчёт останется."""
    folder.mkdir(parents=True, exist_ok=False)
    generate(folder / "input")
    with temporary_postgres() as dsn:
        initialize(dsn)
        receipts = load_batch(dsn, "receipts-01", folder / "input/receipts.csv")
        repeat = load_batch(dsn, "receipts-01", folder / "input/receipts.csv")
        dispatch = load_batch(dsn, "dispatch-01", folder / "input/dispatch.csv")
        before = snapshot(dsn)
        rejected = []
        for case, failure in [("negative", False), ("conflict", False), ("failure", True)]:
            try:
                load_batch(dsn, case + "-01", folder / "input" / (case + ".csv"), fail_before_commit=failure)
            except (DataError, DemoFailure):
                rejected.append(case)
            else:
                raise AssertionError("Учебный ошибочный сценарий неожиданно прошёл.")
            assert snapshot(dsn) == before, "Откат обязан сохранить прежнюю сводку."
        result = {"receipts": receipts, "repeat": repeat, "dispatch": dispatch,
                  "rejected_without_changes": rejected, "snapshot": before}
    # Это уже обычные файлы; технической базы и пароля в них нет.
    (folder / "result.json").write_text(json_text(result), encoding="utf-8")
    lines = ["# Мини-склад", "", "Данные синтетические; остаток после двух принятых партий.", "",
             "| SKU | Остаток |", "| --- | --- |"]
    lines += [f"| {r['sku']} | {r['quantity']} |" for r in before["balances"]]
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Учебный мини-склад на PostgreSQL")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, default in [("demo", "workspace/demo"), ("sample", "workspace/input")]:
        command = commands.add_parser(name, help="Одноразовое демо" if name == "demo" else "Создать учебные CSV")
        command.add_argument("--output", type=Path, default=Path(default), help="Новая папка; прежняя не перезаписывается")
    commands.add_parser("init", help="Создать свою схему в базе из STOCK_DSN")
    load = commands.add_parser("load", help="Принять партию в базе из STOCK_DSN")
    load.add_argument("--input", type=Path, required=True, help="CSV с event_id,sku,delta")
    load.add_argument("--batch", required=True, help="Устойчивый ключ логической загрузки")
    load.add_argument("--fail-before-commit", action="store_true", help="Учебный отказ после INSERT")
    commands.add_parser("report", help="Показать согласованный JSON остатков из STOCK_DSN")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            print(json_text(demo(args.output)), end="")
        elif args.command == "sample":
            generate(args.output)
            print("Созданы 5 синтетических CSV. Существующие папки не менялись.")
        else:
            dsn = os.environ.get("STOCK_DSN")
            if not dsn:
                raise DataError("Для init/load/report задай STOCK_DSN; для самостоятельного примера используй demo.")
            if args.command == "init":
                initialize(dsn)
                print("Учебная схема готова; прежние события сохранены.")
            elif args.command == "load":
                print(json_text(load_batch(dsn, args.batch, args.input,
                                          fail_before_commit=args.fail_before_commit)), end="")
            else:
                print(json_text(snapshot(dsn)), end="")
    except FileExistsError:
        print("Папка уже существует. Выбери другое --output, чтобы сохранить прежние данные.", file=sys.stderr)
        return 1
    except (DataError, DemoFailure, OSError, RuntimeError, psycopg.Error) as exc:
        # Драйвер может включить DSN в подробности ошибки; наружу отдаём безопасное сообщение.
        detail = str(exc) if isinstance(exc, (DataError, DemoFailure)) else "Проверь PostgreSQL 16, PG_BIN, доступ к папке и соединение; инструкция в README."
        print(type(exc).__name__ + ": " + detail, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
