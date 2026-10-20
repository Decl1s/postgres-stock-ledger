-- DISTINCT удаляет только одинаковые тройки. Конфликтующие ID проверены до вставки.
-- ON CONFLICT — страховка уникального event_id, а не замена проверки содержимого.
INSERT INTO stock_lab.events (event_id, sku, delta, batch_id)
SELECT DISTINCT event_id, sku, delta, %s FROM incoming
ON CONFLICT (event_id) DO NOTHING
RETURNING event_id;
