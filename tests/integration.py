"""Реальный PostgreSQL: тестовый кластер свой, либо явно названная CI-база stock_test.

TRUNCATE используется только внутри этой тестовой среды. В приложении его нет.
Если сервер недоступен, тесты падают, а не отображают фиктивный success через skip.
"""

import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from stock_ledger.core import DataError, DemoFailure, connect, initialize, load_batch, snapshot
from stock_ledger.examples import generate, write_csv
from stock_ledger.lab import temporary_postgres


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = None
        if os.environ.get("STOCK_TEST_DSN"):
            cls.dsn = os.environ["STOCK_TEST_DSN"]
            if conninfo_to_dict(cls.dsn).get("dbname") != "stock_test":
                raise RuntimeError("Внешние тесты допускаются только в отдельной базе stock_test.")
        else:
            cls.server = temporary_postgres()
            cls.dsn = cls.server.__enter__()
            cls.addClassCleanup(cls.server.__exit__, None, None, None)
        initialize(cls.dsn)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        generate(self.root / "input")
        with connect(self.dsn) as conn:
            conn.execute("TRUNCATE stock_lab.events, stock_lab.batches")

    def load(self, case="receipts", key=None, **kwargs):
        return load_batch(self.dsn, key or case, self.root / "input" / (case + ".csv"), **kwargs)

    def test_copy_dedup_and_balances(self):
        result = self.load()
        self.assertEqual((result["input_rows"], result["unique_events"], result["inserted_events"]), (4, 3, 3))
        self.load("dispatch")
        report = snapshot(self.dsn)
        self.assertEqual(report["balances"], [{"sku": "BAG", "quantity": 3},
                                             {"sku": "BOOK", "quantity": 7}, {"sku": "PEN", "quantity": 16}])
        self.assertEqual(report["events"], 6)
        self.assertEqual(len(report["batches"]), 2)

    def test_same_batch_is_reused(self):
        self.load()
        before = snapshot(self.dsn)
        self.assertTrue(self.load()["reused"])
        self.assertEqual(snapshot(self.dsn), before)

    def test_same_batch_changed_bytes_refused(self):
        self.load()
        path = self.root / "input/receipts.csv"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        before = snapshot(self.dsn)
        with self.assertRaises(DataError):
            self.load()
        self.assertEqual(snapshot(self.dsn), before)

    def test_same_events_in_new_batch_not_counted_again(self):
        self.load()
        result = self.load(key="second")
        self.assertEqual(result["inserted_events"], 0)
        self.assertEqual(snapshot(self.dsn)["events"], 3)
        self.assertEqual(len(snapshot(self.dsn)["batches"]), 2)

    def test_conflict_inside_batch_rolls_back(self):
        source = self.root / "mixed.csv"
        write_csv(source, [("E0001", "BOOK", 10), ("E0001", "BOOK", 11)])
        with self.assertRaises(DataError):
            load_batch(self.dsn, "mixed", source)
        self.assertEqual(snapshot(self.dsn), {"events": 0, "balances": [], "batches": []})

    def test_conflict_with_saved_event_rolls_back(self):
        self.load()
        before = snapshot(self.dsn)
        with self.assertRaises(DataError):
            self.load("conflict")
        self.assertEqual(snapshot(self.dsn), before)

    def test_negative_stock_rolls_back_good_and_bad_events(self):
        self.load()
        before = snapshot(self.dsn)
        with self.assertRaises(DataError):
            self.load("negative")
        self.assertEqual(snapshot(self.dsn), before)

    def test_exception_after_insert_and_recovery(self):
        self.load()
        before = snapshot(self.dsn)
        with self.assertRaises(DemoFailure):
            self.load("failure", fail_before_commit=True)
        self.assertEqual(snapshot(self.dsn), before)
        self.assertEqual(self.load("failure")["inserted_events"], 1)

    def test_initialize_preserves_existing_rows(self):
        self.load()
        before = snapshot(self.dsn)
        initialize(self.dsn)
        self.assertEqual(snapshot(self.dsn), before)

    def test_database_check_constraint_is_real(self):
        self.load()
        with connect(self.dsn) as conn:
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute("INSERT INTO stock_lab.events VALUES (%s, %s, %s, %s)",
                             ("E9999", "BOOK", 0, "receipts"))
        self.assertEqual(snapshot(self.dsn)["events"], 3)

    def test_concurrent_same_batch_one_commit(self):
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait(timeout=5)
            return self.load()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(sorted(r["reused"] for r in results), [False, True])
        self.assertEqual(snapshot(self.dsn)["events"], 3)

    def test_concurrent_withdrawals_cannot_overdraw(self):
        self.load()
        paths = [self.root / "a.csv", self.root / "b.csv"]
        for number, path in enumerate(paths, start=4):
            write_csv(path, [("E000" + str(number), "BOOK", -7)])
        barrier = threading.Barrier(2)

        def worker(index):
            barrier.wait(timeout=5)
            try:
                load_batch(self.dsn, "out" + str(index), paths[index])
                return "accepted"
            except DataError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(sorted(results), ["accepted", "rejected"])
        self.assertEqual(next(r["quantity"] for r in snapshot(self.dsn)["balances"] if r["sku"] == "BOOK"), 3)

    def test_writer_waits_for_existing_transaction(self):
        started = threading.Event()

        def worker():
            started.set()
            return self.load()

        with connect(self.dsn) as conn, ThreadPoolExecutor(max_workers=1) as pool:
            with conn.transaction():
                conn.execute("LOCK TABLE stock_lab.batches, stock_lab.events IN SHARE ROW EXCLUSIVE MODE")
                future = pool.submit(worker)
                self.assertTrue(started.wait(timeout=3))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.2)
            self.assertEqual(future.result(timeout=5)["inserted_events"], 3)


if __name__ == "__main__":
    unittest.main()
