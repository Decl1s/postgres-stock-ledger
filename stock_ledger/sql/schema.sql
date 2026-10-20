-- Эта схема создаётся только явной командой init или внутри отдельного демо-кластера.
-- DROP отсутствует: пользовательская база не очищается ради запуска примера.
CREATE SCHEMA stock_lab;
CREATE TABLE stock_lab.meta (
    singleton boolean PRIMARY KEY CHECK (singleton),
    schema_version integer NOT NULL CHECK (schema_version = 1)
);
INSERT INTO stock_lab.meta VALUES (true, 1);

-- batch_id — ключ загрузки, source_sha256 — проверка неизменности её входных байтов.
CREATE TABLE stock_lab.batches (
    batch_id text PRIMARY KEY CHECK (batch_id ~ '^[a-z][a-z0-9_-]{0,39}$'),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    input_rows integer NOT NULL CHECK (input_rows BETWEEN 1 AND 10000),
    unique_events integer NOT NULL CHECK (unique_events BETWEEN 1 AND input_rows),
    inserted_events integer NOT NULL CHECK (inserted_events BETWEEN 0 AND unique_events),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Не обновляем события: исправление движения — новое компенсирующее событие.
-- FK не допускает событие без зарегистрированной партии в той же транзакции.
CREATE TABLE stock_lab.events (
    event_id text PRIMARY KEY CHECK (event_id ~ '^E[0-9]{4}$'),
    sku text NOT NULL CHECK (sku ~ '^[A-Z][A-Z0-9_]{1,15}$'),
    delta integer NOT NULL CHECK (delta BETWEEN -99999 AND 99999 AND delta <> 0),
    batch_id text NOT NULL REFERENCES stock_lab.batches(batch_id)
);

-- Остаток не дублируется в отдельной изменяемой таблице: источник истины — события.
CREATE VIEW stock_lab.balances AS
SELECT sku, sum(delta) AS quantity FROM stock_lab.events GROUP BY sku;
