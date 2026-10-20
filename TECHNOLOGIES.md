# Технологии и закреплённые зависимости

Версия 0.1.0, 20.10.2026. Новая основная технология — PostgreSQL.

| Компонент | Фактическая версия | Назначение и официальный источник |
| --- | --- | --- |
| PostgreSQL server | 16.15 локально; демо принимает установленный 16.x | Транзакции, SQL, PK/FK/CHECK, блокировки и снимки: https://www.postgresql.org/docs/16/ |
| initdb, pg_ctl, pg_config | 16.15, уже установлены | Создать/остановить свой временный кластер и найти серверный bin: https://www.postgresql.org/docs/16/app-pg-ctl.html |
| Psycopg | 3.3.6 | Драйвер Python, COPY FROM STDIN, параметры и контексты транзакций: https://pypi.org/project/psycopg/3.3.6/ |
| libpq | 18.6, pq.version()=180006; binary implementation | Клиентский протокол внутри psycopg-binary, фактически подключён к серверу 16.15: https://www.postgresql.org/docs/18/libpq.html |
| SCRAM-SHA-256 | Механизм PostgreSQL 16 | Аутентификация отдельного временного кластера; пароль генерируется secrets: https://www.postgresql.org/docs/16/auth-password.html |
| Python | 3.12.x, локально 3.12.14 | CLI, контракт CSV, управление окружением и тесты: https://docs.python.org/3.12/ |
| uv | 0.13.1 | Локальная .venv, lock-файл с маркерами и хэшами: https://pypi.org/project/uv/0.13.1/ |
| SQL | PostgreSQL 16 | TEMP staging, DISTINCT, ON CONFLICT, RETURNING, GROUP BY и LOCK: https://www.postgresql.org/docs/16/sql.html |
| CSV / JSON / Markdown | UTF-8 | Учебный вход, машинные снимки и отчёт: https://docs.python.org/3.12/library/csv.html |
| unittest / mock | Python 3.12 standard library | Быстрые и настоящие интеграционные проверки: https://docs.python.org/3.12/library/unittest.html |
| ThreadPoolExecutor | Python 3.12 standard library | Два конкурирующих клиента в интеграционных тестах: https://docs.python.org/3.12/library/concurrent.futures.html |
| SHA-256 / ZIP | hashlib / zipfile standard library | Проверка входа и исходный архив по allowlist: https://docs.python.org/3.12/library/hashlib.html |
| Git | Локально 2.43.0 | Собственный репозиторий и ветка codex/: https://git-scm.com/docs |
| VS Code | 1.140.0, уже установлен | Учебные задачи и конфигурации отладки: https://code.visualstudio.com/docs |
| ms-python.python / debugpy | 2026.6.0, уже установлены | Python проекта, unittest и F5; не зависимость CLI: https://marketplace.visualstudio.com/items?itemName=ms-python.python |
| Pylance | 2026.4.1, уже установлен | Подсказки/навигация Python, необязательно для запуска: https://marketplace.visualstudio.com/items?itemName=ms-python.vscode-pylance |
| Mermaid | Разметка NOTES.md | Статическая схема этапов: https://mermaid.js.org/ |
| GitHub Actions | Быстрые тесты Ubuntu/Windows; БД Ubuntu — пройдены | Проверки и архив после публикации: https://docs.github.com/ru/actions |
| actions/checkout | v4, SHA в ci.yml | Исходники без сохранения credentials: https://github.com/actions/checkout |
| actions/setup-python | v5, SHA в ci.yml | Python 3.12 на CI runner: https://github.com/actions/setup-python |
| actions/upload-artifact | v4, SHA в ci.yml | ZIP/SHA256SUMS как артефакт: https://github.com/actions/upload-artifact |
| Docker official postgres | 16.15, проверенный CI service | Отдельная база stock_test для интеграции; локально Docker не использовался: https://hub.docker.com/_/postgres |

## Полный Python lock

Прямая зависимость: psycopg[binary]==3.3.6. Остальные пакеты ниже — транзитивные,
включая платформенные. На Linux установлены psycopg, psycopg-binary и typing-extensions;
tzdata условный для Windows. uv.lock содержит версии, маркеры ОС, URL и хэши колёс.
Binary-поставка не требует системного C-компилятора. Версию библиотек обновлять через
uv с повторными проверками; сам lock руками не редактировать.

| Пакет | Версия | Назначение / официальный источник |
| --- | --- | --- |
| psycopg | 3.3.6 | Прямой Python-драйвер: https://pypi.org/project/psycopg/3.3.6/ |
| psycopg-binary | 3.3.6 | Бинарная реализация и клиентская libpq: https://pypi.org/project/psycopg-binary/3.3.6/ |
| typing-extensions | 4.16.0 | Совместимость аннотаций типов: https://pypi.org/project/typing-extensions/4.16.0/ |
| tzdata | 2026.5 | Условные данные часовых поясов Windows: https://pypi.org/project/tzdata/2026.5/ |

Стандартная библиотека: argparse, csv, hashlib, io, json, os, pathlib, re, secrets,
shutil, socket, subprocess, sys, tempfile, contextlib, concurrent.futures, threading,
unittest, unittest.mock, importlib.util, tomllib и zipfile. pip из bootstrap — только
способ установить uv локально; дополнительная runtime-зависимость не нужна.
Python ограничен веткой 3.12. Сервер использует имеющийся дистрибутив PostgreSQL,
не устанавливается из pip/uv и не входит в ZIP. Локальная ОС Linux amd64.

Официальная версия сервера проверена по release-16-15.html (13.08.2026), Psycopg
3.3.6 — по PyPI (18.09.2026). PostgreSQL 16 выбран по доступности и задаче, не как
самая новая основная версия. Службы и глобальные компоненты не устанавливались.
