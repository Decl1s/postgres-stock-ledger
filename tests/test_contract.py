"""Быстрые проверки контракта/CLI не требуют сервера и не пропускаются молча."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_ledger.core import DataError, load_batch, read_csv
from stock_ledger.examples import generate


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "input"
        generate(self.folder)
        self.source = self.folder / "receipts.csv"

    def test_generated_rows_and_duplicates_remain_for_sql(self):
        value = read_csv(self.source)
        self.assertEqual(len(value["events"]), 4)
        self.assertEqual(value["events"][0], ("E0001", "BOOK", 10))
        self.assertEqual(value["events"][0], value["events"][-1])

    def test_invalid_fields(self):
        original = self.source.read_text()
        for old, new in [("E0001", "X0001"), ("BOOK", "bo'ok"), ("BOOK", "B"),
                         (",10", ",0"), (",10", ",+10"), (",10", ",01"), (",10", ",1.5"),
                         (",10", ",100000"), (",10", ",-100000"), ("event_id", "id")]:
            with self.subTest(new=new):
                self.source.write_text(original.replace(old, new), encoding="utf-8")
                with self.assertRaises(DataError):
                    read_csv(self.source)

    def test_empty_ragged_and_malformed_csv(self):
        for text in ["", "event_id,sku,delta\n", "event_id,sku,delta\nE0001,BOOK\n",
                     'event_id,sku,delta\n"unclosed']:
            with self.subTest(text=text[:10]):
                self.source.write_text(text, encoding="utf-8")
                with self.assertRaises(DataError):
                    read_csv(self.source)

    def test_byte_and_row_limits(self):
        with patch("stock_ledger.core.MAX_BYTES", 10):
            with self.assertRaises(DataError):
                read_csv(self.source)
        with patch("stock_ledger.core.MAX_ROWS", 3):
            with self.assertRaises(DataError):
                read_csv(self.source)

    def test_utf8_bom_and_crlf(self):
        before = read_csv(self.source)
        self.source.write_bytes(b"\xef\xbb\xbf" + self.source.read_bytes().replace(b"\n", b"\r\n"))
        after = read_csv(self.source)
        self.assertEqual(before["events"], after["events"])
        self.assertNotEqual(before["sha256"], after["sha256"])

    def test_bad_encoding_and_missing_file(self):
        self.source.write_bytes(b"\xff")
        with self.assertRaises(DataError):
            read_csv(self.source)
        self.source.unlink()
        with self.assertRaises(DataError):
            read_csv(self.source)

    def test_generator_preserves_existing_edits(self):
        self.source.write_text("synthetic edit", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            generate(self.folder)
        self.assertEqual(self.source.read_text(), "synthetic edit")

    def test_batch_id_rejected_before_connect(self):
        with patch("stock_ledger.core.connect") as connection:
            for key in ["", "Bad", "x';DROP", "a" * 41]:
                with self.subTest(key=key), self.assertRaises(DataError):
                    load_batch("", key, self.source)
            connection.assert_not_called()

    def test_cli_missing_dsn_does_not_print_credentials(self):
        result = subprocess.run([sys.executable, "-m", "stock_ledger", "report"], capture_output=True,
                                env={key: value for key, value in os.environ.items() if key != "STOCK_DSN"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("STOCK_DSN", result.stderr.decode("utf-8"))

    def test_cli_sample_and_repeat(self):
        target = Path(self.temp.name) / "cli"
        command = [sys.executable, "-m", "stock_ledger", "sample", "--output", str(target)]
        first = subprocess.run(command, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        again = subprocess.run(command, capture_output=True)
        self.assertEqual(again.returncode, 1)
        self.assertEqual(len(list(target.glob("*.csv"))), 5)


if __name__ == "__main__":
    unittest.main()
