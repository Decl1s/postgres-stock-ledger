"""Одноразовый локальный PostgreSQL из уже установленного официального дистрибутива.

Не обращается к системному кластеру, не устанавливает службу и не меняет его файлы.
Возвращаемый DSN содержит случайный пароль: его нельзя печатать или сохранять в отчёт.
"""

import os
import secrets
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from psycopg.conninfo import make_conninfo


def postgres_bin() -> Path:
    """PG_BIN — явный путь; иначе PATH или pg_config --bindir. Никакого скачивания."""
    suffix = ".exe" if os.name == "nt" else ""
    if os.environ.get("PG_BIN"):
        folder = Path(os.environ["PG_BIN"])
    elif os.name == "posix" and Path("/usr/lib/postgresql/16/bin/initdb").is_file():
        # В Ubuntu могут сосуществовать версии: pg_config по умолчанию уже указывает на 18.
        # Для этого учебного проекта сохраняем требуемый сервер 16.
        folder = Path("/usr/lib/postgresql/16/bin")
    elif shutil.which("initdb"):
        folder = Path(shutil.which("initdb")).parent
    elif shutil.which("pg_config"):
        result = subprocess.run(["pg_config", "--bindir"], capture_output=True, text=True, check=True)
        folder = Path(result.stdout.strip())
    else:
        raise RuntimeError("Нужен установленный PostgreSQL 16; укажи его bin через PG_BIN.")
    if not all((folder / (name + suffix)).is_file() for name in ("initdb", "pg_ctl")):
        raise RuntimeError("В PG_BIN не найдены initdb и pg_ctl.")
    version = subprocess.run([str(folder / ("initdb" + suffix)), "--version"],
                             capture_output=True, text=True, check=True).stdout
    if " 16." not in version:
        raise RuntimeError("Учебный запуск рассчитан на сервер PostgreSQL 16.x.")
    return folder


@contextmanager
def temporary_postgres():
    """Запустить свой кластер, затем остановить его и удалить только свою папку.

Порт выбирается свободным на момент проверки; редкая гонка запуска даст понятный
отказ. Unix socket отключён, чтобы длинный путь проекта не превышал предел ОС.
"""
    binary = postgres_bin()
    suffix = ".exe" if os.name == "nt" else ""
    runtime = Path("workspace/runtime").absolute()
    runtime.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="stock-pg-", dir=runtime))
    data = folder / "data"
    secret = folder / "password.txt"
    password = secrets.token_urlsafe(24)
    secret.write_text(password + "\n", encoding="utf-8")
    secret.chmod(0o600)
    # Только дочерние команды: чужие PGHOST/PGDATA/PGOPTIONS не переопределят кластер.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    ctl = str(binary / ("pg_ctl" + suffix))
    try:
        result = subprocess.run([str(binary / ("initdb" + suffix)), "-D", str(data), "-U", "lab_owner",
                                 "--pwfile=" + str(secret), "--auth-local=scram-sha-256",
                                 "--auth-host=scram-sha-256", "--no-locale", "--encoding=UTF8"],
                                capture_output=True, env=env, timeout=60)
        if result.returncode:
            raise RuntimeError("Не удалось создать отдельный кластер; проверь PostgreSQL 16 и права папки.")
        secret.unlink()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        (data / "postgresql.auto.conf").write_text(
            "listen_addresses = '127.0.0.1'\nport = " + str(port) +
            "\nunix_socket_directories = ''\nmax_connections = 20\n", encoding="utf-8")
        result = subprocess.run([ctl, "-D", str(data), "-l", str(folder / "server.log"),
                                 "-w", "-t", "30", "start"], capture_output=True, env=env, timeout=40)
        if result.returncode:
            raise RuntimeError("Временный PostgreSQL не запустился; проверь локальные сокеты и порт.")
        yield make_conninfo(host="127.0.0.1", port=port, dbname="postgres", user="lab_owner", password=password)
    finally:
        # Не удаляем PGDATA из-под работающего сервера при неудачной остановке.
        if (data / "postmaster.pid").exists():
            subprocess.run([ctl, "-D", str(data), "-m", "fast", "-w", "-t", "20", "stop"],
                           capture_output=True, env=env, timeout=30)
        if (data / "postmaster.pid").exists():
            raise RuntimeError("Сервер не остановлен; его собственная папка сохранена для ручной диагностики.")
        shutil.rmtree(folder)
