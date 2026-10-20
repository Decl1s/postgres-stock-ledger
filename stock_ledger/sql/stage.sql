-- Временная таблица принадлежит одному соединению и исчезает при COMMIT.
-- Здесь допустимы повторы: их нужно отличить от конфликтующих ID, а не молча потерять.
CREATE TEMP TABLE incoming (
    event_id text NOT NULL,
    sku text NOT NULL,
    delta integer NOT NULL
) ON COMMIT DROP;
