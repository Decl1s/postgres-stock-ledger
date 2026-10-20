"""Контракт CSV и граница транзакции. Начни с read_csv → load_batch → snapshot.

Данные передаются параметрами/copy.write_row, не собираются в SQL строковой подстановкой.
Остаток проверяется внутри той же транзакции, которая вставляет события и партию.
"""

import csv
import hashlib
import io
import re
from pathlib import Path

import psycopg

SQL = Path(__file__).with_name("sql")
MAX_BYTES = 1_000_000
MAX_ROWS = 10_000


class DataError(ValueError):
    """Плохой вход/конфликт/отрицательный остаток: повтор не исправляет смысл данных."""


class DemoFailure(RuntimeError):
    """Контролируемый отказ после вставки для демонстрации ROLLBACK."""


def read_csv(path: str | Path) -> dict:
    """Читать небольшой UTF-8 CSV; вернуть хэш исходных байтов и проверенные тройки.

Повторы ID пока сохраняем: их смысл проверит staging в PostgreSQL.
Лимит +1 байт позволяет заметить превышение без чтения огромного файла целиком.
"""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise DataError("Нужен обычный CSV без символических ссылок.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise DataError("CSV больше 1 000 000 байт.")
    try:
        rows = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if next(rows, None) != ["event_id", "sku", "delta"]:
            raise DataError("Ожидается заголовок event_id,sku,delta.")
        events = []
        for index, row in enumerate(rows, start=1):
            if index > MAX_ROWS or len(row) != 3:
                raise DataError("Превышен предел строк или неверно число полей.")
            event_id, sku, delta = row
            if (not re.fullmatch(r"E[0-9]{4}", event_id)
                    or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,15}", sku)
                    or not re.fullmatch(r"-?[1-9][0-9]{0,4}", delta)):
                raise DataError(f"Строка данных {index}: нарушен контракт ID, SKU или delta.")
            events.append((event_id, sku, int(delta)))
        if not events:
            raise DataError("Пустая партия не допускается.")
    except (UnicodeError, csv.Error) as exc:
        raise DataError("Нужен корректный CSV UTF-8.") from exc
    return {"sha256": hashlib.sha256(raw).hexdigest(), "events": events}


def connect(dsn: str):
    """Явные короткие таймауты; DSN с паролем никогда не печатаем."""
    return psycopg.connect(dsn, autocommit=True, connect_timeout=5,
                           application_name="stock-lab",
                           options="-c statement_timeout=5000 -c lock_timeout=3000")


def verify_schema(conn) -> None:
    """Не пытаться угадать миграцию чужой схемы; версия должна быть ровно 1."""
    if conn.execute("SELECT schema_version FROM stock_lab.meta WHERE singleton").fetchone() != (1,):
        raise DataError("Неизвестная версия схемы склада.")


def initialize(dsn: str) -> None:
    """Создать только свою отсутствующую схему; повтор сохраняет данные."""
    with connect(dsn) as conn, conn.transaction():
        if conn.execute("SELECT to_regnamespace('stock_lab')").fetchone()[0] is None:
            conn.execute((SQL / "schema.sql").read_text(encoding="utf-8"))
        verify_schema(conn)


def load_batch(dsn: str, batch_id: str, path: str | Path, *, fail_before_commit: bool = False) -> dict:
    """Атомарно принять весь пакет или откатить все его изменения.

batch_id — имя логической загрузки. Тот же ключ с другим содержимым запрещён.
Одинаковый event_id в другом пакете пропускаем только при совпадении sku и delta.
fail_before_commit — учебное исключение после INSERT, а не имитация сбоя питания.
"""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", batch_id):
        raise DataError("Неверный batch_id: строчные буквы, цифры, _ и -, до 40 символов.")
    source = read_csv(path)
    with connect(dsn) as conn, conn.transaction():
        verify_schema(conn)
        # Один писатель на мини-склад. Обычные SELECT продолжают работать.
        # При READ COMMITTED следующий SELECT после ожидания увидит уже принятый пакет.
        # Один порядок блокировок для всех загрузок уменьшает риск deadlock.
        conn.execute("LOCK TABLE stock_lab.batches, stock_lab.events IN SHARE ROW EXCLUSIVE MODE")
        existing = conn.execute("SELECT source_sha256, input_rows, unique_events, inserted_events "
                                "FROM stock_lab.batches WHERE batch_id = %s", (batch_id,)).fetchone()
        if existing:
            if existing[0] != source["sha256"]:
                raise DataError("batch_id уже принят с другими входными байтами.")
            return {"batch_id": batch_id, "reused": True, "input_rows": existing[1],
                    "unique_events": existing[2], "inserted_events": existing[3]}
        conn.execute((SQL / "stage.sql").read_text(encoding="utf-8"))
        # COPY FROM STDIN идёт через соединение: сервер не читает путь на диске клиента.
        with conn.cursor().copy("COPY incoming (event_id, sku, delta) FROM STDIN") as copy:
            for event in source["events"]:
                copy.write_row(event)
        conflict = conn.execute("SELECT event_id FROM incoming GROUP BY event_id "
                                "HAVING count(DISTINCT (sku, delta)) > 1 LIMIT 1").fetchone()
        if conflict:
            raise DataError("Один event_id содержит разные события внутри партии.")
        conflict = conn.execute("SELECT i.event_id FROM incoming i JOIN stock_lab.events e USING (event_id) "
                                "WHERE (i.sku, i.delta) IS DISTINCT FROM (e.sku, e.delta) LIMIT 1").fetchone()
        if conflict:
            raise DataError("event_id уже сохранён с другим SKU или delta.")
        unique = conn.execute("SELECT count(DISTINCT event_id) FROM incoming").fetchone()[0]
        # Сначала родительская партия, потом её события: FK проверяется сразу.
        conn.execute("INSERT INTO stock_lab.batches VALUES (%s, %s, %s, %s, 0, DEFAULT)",
                     (batch_id, source["sha256"], len(source["events"]), unique))
        inserted = len(conn.execute((SQL / "insert.sql").read_text(encoding="utf-8"), (batch_id,)).fetchall())
        if conn.execute("SELECT sku FROM stock_lab.balances WHERE quantity < 0 LIMIT 1").fetchone():
            raise DataError("Партия дала бы отрицательный остаток; изменения откатываются.")
        conn.execute("UPDATE stock_lab.batches SET inserted_events = %s WHERE batch_id = %s",
                     (inserted, batch_id))
        if fail_before_commit:
            raise DemoFailure("Учебный отказ после INSERT перед COMMIT.")
        # Выход из conn.transaction() выполнит COMMIT до возврата вызывающему коду.
        return {"batch_id": batch_id, "reused": False, "input_rows": len(source["events"]),
                "unique_events": unique, "inserted_events": inserted}


def snapshot(dsn: str) -> dict:
    """Согласованная сводка: несколько SELECT читают один снимок REPEATABLE READ."""
    with connect(dsn) as conn, conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        verify_schema(conn)
        balances = [{"sku": sku, "quantity": qty} for sku, qty in
                    conn.execute("SELECT sku, quantity FROM stock_lab.balances ORDER BY sku")]
        events = conn.execute("SELECT count(*) FROM stock_lab.events").fetchone()[0]
        batches = [{"batch_id": key, "input_rows": rows, "unique_events": unique, "inserted_events": inserted}
                   for key, rows, unique, inserted in conn.execute(
                       "SELECT batch_id, input_rows, unique_events, inserted_events FROM stock_lab.batches ORDER BY batch_id")]
        return {"balances": balances, "events": events, "batches": batches}
