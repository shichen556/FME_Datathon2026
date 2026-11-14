-- SQL examples for the RawTree challenge. Run them with the CLI, the HTTP API or the MCP server:
--   rtree query --api-key $RAWTREE_API_KEY --database $TEAM_ID "<sql>"
--   curl -s https://api.rawtree.com/v1/query -H "Authorization: Bearer $RAWTREE_API_KEY" -d '{"sql":"<sql>"}'
-- Replace team_NN with your team database.
--
-- RawTree is schemaless: every column is Dynamic (each value keeps its own type). Filters, ORDER BY and most
-- functions just work; JOIN keys, argMax/argMin and some aggregates need a cast: product_id::String, ts::DateTime64(3).


-- 1. Current catalogue: shop.catalog with the latest shop.catalog_updates record of each product on top
SELECT product_id,
       argMax(category, v)    AS category,
       argMax(subcategory, v) AS subcategory,
       argMax(price_eur, v)   AS price_eur,
       argMax(is_active, v)   AS is_active
FROM (
    SELECT product_id::String AS product_id, category::String AS category, subcategory::String AS subcategory,
           price_eur::Float64 AS price_eur, is_active::Bool AS is_active, '' AS v
    FROM shop.catalog
    UNION ALL
    SELECT product_id::String, category::String, subcategory::String, price_eur::Float64, is_active::Bool, toString(ts)
    FROM shop.catalog_updates
)
GROUP BY product_id;


-- 2. Popularity per category in the last hour (live organic activity)
SELECT c.category::String AS category, e.product_id::String AS product_id,
       countIf(e.event_type = 'view')     AS views,
       countIf(e.event_type = 'purchase') AS purchases
FROM shop.events AS e
INNER JOIN shop.catalog AS c ON c.product_id::String = e.product_id::String
WHERE e.ts > now() - INTERVAL 1 HOUR
GROUP BY category, product_id
ORDER BY purchases DESC, views DESC
LIMIT 5 BY category;


-- 3. What is trending right now? Views per subcategory, last 15 minutes vs the 3 hours before
SELECT c.subcategory::String AS subcategory,
       countIf(e.ts > now() - INTERVAL 15 MINUTE)        AS views_15m,
       countIf(e.ts <= now() - INTERVAL 15 MINUTE) / 12  AS avg_views_per_15m_before,
       views_15m / greatest(avg_views_per_15m_before, 1) AS lift
FROM shop.events AS e
INNER JOIN shop.catalog AS c ON c.product_id::String = e.product_id::String
WHERE e.event_type = 'view' AND e.ts > now() - INTERVAL 195 MINUTE
GROUP BY subcategory
ORDER BY lift DESC
LIMIT 10;


-- 4. Co-views: products viewed in the same session as a given product (history)
SELECT b.product_id AS also_viewed, count() AS sessions
FROM (SELECT session_id::String AS session_id, product_id::String AS product_id FROM shop.history_events WHERE event_type = 'view') AS a
INNER JOIN (SELECT session_id::String AS session_id, product_id::String AS product_id FROM shop.history_events WHERE event_type = 'view') AS b
    ON a.session_id = b.session_id
WHERE a.product_id = 'p_xxxxxx' AND b.product_id != a.product_id
GROUP BY also_viewed
ORDER BY sessions DESC
LIMIT 20;


-- 5. Your feedback: conversion and revenue per hour, split by who served the shopper
-- (clicked / purchased are '' when nothing happened)
SELECT toStartOfHour(ts::DateTime64(3)) AS hour,
       served_by::String                   AS served_by,
       count()                             AS requests,
       100 * countIf(clicked != '') / count()   AS ctr_pct,
       100 * countIf(purchased != '') / count() AS conversion_pct,
       sum(revenue_eur::Float64) / count()      AS revenue_per_request
FROM team_NN.feedback
WHERE request_id != '__init__'
GROUP BY hour, served_by
ORDER BY hour DESC, served_by;


-- 6. Reliability: why did the fallback serve your shoppers, and how fast are you?
SELECT fallback_reason::String              AS fallback_reason,
       count()                              AS requests,
       quantile(0.5)(latency_ms::Float64)   AS p50_ms,
       quantile(0.95)(latency_ms::Float64)  AS p95_ms
FROM team_NN.feedback
WHERE ts > now() - INTERVAL 30 MINUTE AND request_id != '__init__'
GROUP BY fallback_reason;


-- 7. Which slots get clicked? (position bias in the old system's log)
SELECT indexOf(shown, clicked) AS slot, count() AS clicks
FROM shop.history_sessions
WHERE clicked IS NOT NULL
GROUP BY slot
ORDER BY slot;
