-- 1. Tasa de conversión según el tipo de página (home, product, category) y dispositivo
SELECT
    context.page::String   AS page,
    context.device::String AS device,
    count()                AS sessions,
    round(100 * countIf(clicked != '') / count(), 2)   AS ctr_pct,
    round(100 * countIf(purchased != '') / count(), 2) AS conv_pct,
    round(avg(revenue_eur::Float64), 3)                AS avg_rev
FROM shop.history_sessions
GROUP BY page, device
ORDER BY sessions DESC;

-- 2. ¿Con qué frecuencia el usuario compra un producto que YA había visto o añadido al carrito en la sesión?
SELECT
    countIf(purchased != '')                                              AS total_purchases,
    countIf(purchased != '' AND has(recent_views.product_id, purchased))  AS bought_from_recent_views,
    round(100 * bought_from_recent_views / greatest(total_purchases, 1), 2) AS pct_retarget
FROM shop.history_sessions;

-- 3. Embudo orgánico en history_events: ratio view -> add_to_cart -> purchase
SELECT
    event_type::String AS event_type,
    count()            AS total_events,
    uniqExact(user_id::String) AS unique_users
FROM shop.history_events
GROUP BY event_type;

-- 4. Sensibilidad al precio por región / dispositivo
SELECT
    s.context.region::String AS region,
    s.context.device::String AS device,
    round(avg(c.price_eur::Float64), 2) AS avg_purchased_price,
    count() AS purchases
FROM shop.history_sessions AS s
INNER JOIN shop.catalog AS c ON s.purchased::String = c.product_id::String
WHERE s.purchased != ''
GROUP BY region, device
ORDER BY purchases DESC;

-- 5. Diagnóstico actual de tu sistema en vivo (si ya corriste el starter)
SELECT
    served_by::String AS served_by,
    fallback_reason::String AS reason,
    count() AS n,
    round(quantile(0.95)(latency_ms::Float64), 1) AS p95_ms,
    round(100 * countIf(purchased != '') / count(), 2) AS conv_pct
FROM team_NN.feedback
WHERE request_id != '__init__'
GROUP BY served_by, reason;

-- 6. Team_NN table extraction
SELECT *
    FROM team_34.feedback