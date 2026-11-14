from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

for env_path in [Path(".env"), Path("../.env")]:
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
        break

API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com")
TEAM = os.environ["TEAM_ID"]
MODEL_VERSION = "v2 - Cristian"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {os.environ['RAWTREE_API_KEY']}"
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


hot_http = make_session()
bg_http = make_session()

Record = dict[str, Any]

# --- QUERIES SQL CON CASTS SEGUROS PARA DYNAMIC ---

CURRENT_CATALOG_SQL = """
SELECT
    product_id,
    argMax(raw_category, v)    AS category,
    argMax(raw_subcategory, v) AS subcategory,
    argMax(raw_brand, v)       AS brand,
    argMax(raw_price_eur, v)   AS price_eur,
    argMax(raw_description, v) AS description,
    argMax(raw_is_active, v)   AS is_active,
    argMax(raw_change, v)      AS last_change,
    argMin(raw_price_eur, v)   AS initial_price,
    max(is_new)                AS is_new_product
FROM (
    SELECT
        product_id::String                    AS product_id,
        coalesce(toString(category), '')      AS raw_category,
        coalesce(toString(subcategory), '')   AS raw_subcategory,
        coalesce(toString(brand), '')         AS raw_brand,
        toFloat64OrZero(toString(price_eur))  AS raw_price_eur,
        coalesce(toString(description), '')   AS raw_description,
        coalesce(is_active::Bool, true)       AS raw_is_active,
        ''                                    AS raw_change,
        ''                                    AS v,
        0                                     AS is_new
    FROM shop.catalog
    UNION ALL
    SELECT
        product_id::String,
        coalesce(toString(category), ''),
        coalesce(toString(subcategory), ''),
        coalesce(toString(brand), ''),
        toFloat64OrZero(toString(price_eur)),
        coalesce(toString(description), ''),
        coalesce(is_active::Bool, true),
        coalesce(toString(change), ''),
        toString(ts),
        if(toString(change) = 'new_product', 1, 0)
    FROM shop.catalog_updates
)
GROUP BY product_id
"""

POPULARITY_SQL = """
SELECT
    product_id,
    sum(score) AS total_score
FROM (
    SELECT
        product_id::String AS product_id,
        if(toString(event_type) = 'purchase', 5.0, if(toString(event_type) = 'add_to_cart', 2.0, 0.2)) AS score
    FROM shop.history_events
    UNION ALL
    SELECT
        product_id::String AS product_id,
        if(toString(event_type) = 'purchase', 30.0, if(toString(event_type) = 'add_to_cart', 10.0, 1.5)) AS score
    FROM shop.events
    WHERE ts > now() - INTERVAL 90 MINUTE
)
GROUP BY product_id
ORDER BY total_score DESC
"""

LIVE_USER_EVENTS_SQL = """
SELECT user_id::String AS user_id, toString(event_type) AS event_type, product_id::String AS product_id
FROM shop.events
WHERE ts >= now() - INTERVAL 24 HOUR
  AND (toString(event_type) = 'purchase'
       OR (toString(event_type) = 'add_to_cart' AND ts >= now() - INTERVAL 20 MINUTE))
"""

# Acotado a los últimos 21 días para evitar exceso de memoria en el self-join de 12M filas
CO_PURCHASE_SQL = """
SELECT
    a.product_id AS src,
    b.product_id AS dst,
    sum(a.w)     AS score
FROM (
    SELECT
        session_id::String AS sid,
        product_id::String AS product_id,
        if(toString(event_type) = 'add_to_cart', 3.5, 1.0) AS w
    FROM shop.history_events
    WHERE ts >= now() - INTERVAL 21 DAY
      AND toString(event_type) IN ('view', 'add_to_cart')
) AS a
INNER JOIN (
    SELECT
        session_id::String AS sid,
        product_id::String AS product_id
    FROM shop.history_events
    WHERE ts >= now() - INTERVAL 21 DAY
      AND toString(event_type) = 'purchase'
) AS b ON a.sid = b.sid
WHERE a.product_id != b.product_id
GROUP BY src, dst
ORDER BY src, score DESC
LIMIT 25 BY src
"""

USER_PROFILE_SQL = """
SELECT
    user_id::String AS user_id,
    groupUniqArrayIf(product_id::String, toString(event_type) = 'purchase') AS bought_items,
    topK(6)(product_id::String) AS top_interacted,
    avgIf(toFloat64OrZero(toString(price_eur)), toString(event_type) = 'purchase') AS avg_buy_price
FROM shop.history_events
GROUP BY user_id
"""

CONTEXT_PRICE_SQL = """
SELECT
    s.context.region::String AS region,
    s.context.device::String AS device,
    quantile(0.5)(toFloat64OrZero(toString(c.price_eur))) AS med_price,
    greatest(
        quantile(0.75)(toFloat64OrZero(toString(c.price_eur))) - quantile(0.25)(toFloat64OrZero(toString(c.price_eur))),
        10.0
    ) AS iqr_price
FROM shop.history_sessions AS s
INNER JOIN shop.catalog AS c ON s.purchased::String = c.product_id::String
WHERE s.purchased != ''
GROUP BY region, device
"""

NEW_REQUESTS_SQL = """
SELECT request_id, ts, user_id, is_new_user, context, recent_views
FROM shop.requests
WHERE ts >= now() - INTERVAL 3 SECOND
ORDER BY ts DESC
LIMIT 50
"""

POP_HIST_SQL = """
SELECT product_id::String AS product_id,
       sum(if(toString(event_type)='purchase',5.0,if(toString(event_type)='add_to_cart',2.0,0.2))) AS s
FROM shop.history_events GROUP BY product_id
"""
POP_LIVE_SQL = """
SELECT product_id::String AS product_id,
       sum(if(toString(event_type)='purchase',30.0,if(toString(event_type)='add_to_cart',10.0,1.5))) AS s
FROM shop.events WHERE ts > now() - INTERVAL 90 MINUTE GROUP BY product_id
"""


def run_query(session: requests.Session, sql: str, timeout: float = 15.0) -> list[Record]:
    r = session.post(f"{API}/v1/query", json={"sql": sql}, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:350]}")
    return r.json()["data"]


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


@dataclass
class FastSnapshot:
    active_products: set[str] = field(default_factory=set)
    catalog: dict[str, dict[str, Any]] = field(default_factory=dict)
    pop_rank: list[str] = field(default_factory=list)
    pop_score: dict[str, float] = field(default_factory=dict)
    subcat_top: dict[str, list[str]] = field(default_factory=dict)
    cold_neighbors: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    live_user_carts: dict[str, list[str]] = field(default_factory=dict)
    live_user_bought: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class HeavySnapshot:
    copurchase: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    user_bought: dict[str, set[str]] = field(default_factory=dict)
    user_top: dict[str, list[str]] = field(default_factory=dict)
    user_price: dict[str, float] = field(default_factory=dict)
    ctx_price: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    hist_pop: dict[str, float] = field(default_factory=dict)


class ModelStore:
    def refresh_hist_pop(self) -> None:
        try:
            self.heavy.hist_pop = {str(r["product_id"]): float(r["s"])
                                   for r in run_query(bg_http, POP_HIST_SQL, timeout=45)}
        except Exception as e:
            print(f"[BG] hist_pop warning: {e}")

    def __init__(self) -> None:
        self.fast = FastSnapshot()
        self.heavy = HeavySnapshot()
        self.ready = threading.Event()

    def build_fast_snapshot(self) -> FastSnapshot:
        cat_rows = run_query(bg_http, CURRENT_CATALOG_SQL, timeout=20)
        new_catalog: dict[str, dict[str, Any]] = {}
        new_active: set[str] = set()

        for r in cat_rows:
            pid = str(r["product_id"])
            active = bool(r["is_active"]) and str(r.get("last_change", "")) != "out_of_stock"
            price = float(r["price_eur"] or 0.0)
            init_price = float(r["initial_price"] or price)
            discount = max(0.0, (init_price - price) / init_price) if init_price > 0 else 0.0
            new_catalog[pid] = {
                "category": str(r["category"]),
                "subcategory": str(r["subcategory"]),
                "brand": str(r["brand"]),
                "price": price,
                "discount": discount,
                "is_new": bool(r["is_new_product"]),
                "tokens": tokenize(f"{r['brand']} {r['subcategory']} {r['description']}"),
            }
            if active:
                new_active.add(pid)

        pop_rows = run_query(bg_http, POPULARITY_SQL, timeout=20)
        new_pop_score: dict[str, float] = {}
        new_pop_rank: list[str] = []
        max_pop = float(pop_rows[0]["total_score"]) if pop_rows else 1.0

        for r in pop_rows:
            pid = str(r["product_id"])
            if pid in new_active:
                meta = new_catalog.get(pid, {})
                boost = 1.0 + 1.5 * meta.get("discount", 0.0)
                new_pop_score[pid] = (float(r["total_score"]) / max_pop) * boost
                new_pop_rank.append(pid)

        seen_pop = set(new_pop_rank)
        for pid in new_active:
            if pid not in seen_pop:
                new_pop_rank.append(pid)
                new_pop_score[pid] = 0.01

        new_subcat: dict[str, list[str]] = defaultdict(list)
        for pid in new_pop_rank:
            meta = new_catalog.get(pid)
            if meta and len(new_subcat[meta["subcategory"]]) < 25:
                new_subcat[meta["subcategory"]].append(pid)

        new_cold: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for pid, meta in new_catalog.items():
            if pid not in new_active:
                continue
            if meta["is_new"] or new_pop_score.get(pid, 0.0) < 0.03:
                tok_a = meta["tokens"]
                for peer in new_subcat.get(meta["subcategory"], [])[:15]:
                    if peer == pid:
                        continue
                    tok_b = new_catalog[peer]["tokens"]
                    sim = len(tok_a & tok_b) / max(len(tok_a | tok_b), 1)
                    if meta["brand"] == new_catalog[peer]["brand"]:
                        sim += 0.25
                    new_cold[peer].append((pid, 0.35 + sim))
                    new_cold[pid].append((peer, 0.55 + sim))

        live_carts: dict[str, list[str]] = defaultdict(list)
        live_bought: dict[str, set[str]] = defaultdict(set)
        try:
            for r in run_query(bg_http, LIVE_USER_EVENTS_SQL, timeout=8):
                uid = str(r["user_id"])
                pid = str(r["product_id"])
                if r["event_type"] == "add_to_cart":
                    if pid not in live_carts[uid]:
                        live_carts[uid].append(pid)
                elif r["event_type"] == "purchase":
                    live_bought[uid].add(pid)
        except Exception as e:
            print(f"[BG] live_events warning: {e}")

        return FastSnapshot(
            active_products=new_active,
            catalog=new_catalog,
            pop_rank=new_pop_rank,
            pop_score=new_pop_score,
            subcat_top=dict(new_subcat),
            cold_neighbors=dict(new_cold),
            live_user_carts=dict(live_carts),
            live_user_bought=dict(live_bought),
        )

    def refresh_heavy_parts(self) -> None:
        # Cada parte en su propio bloque para que un fallo aislado no bloquee el resto
        try:
            cp_rows = run_query(bg_http, CO_PURCHASE_SQL, timeout=45)
            raw_cp: dict[str, list[tuple[str, float]]] = defaultdict(list)
            for r in cp_rows:
                raw_cp[str(r["src"])].append((str(r["dst"]), float(r["score"])))
            self.heavy.copurchase = {
                src: [(dst, sc / pairs[0][1]) for dst, sc in pairs]
                for src, pairs in raw_cp.items()
                if pairs
            }
            print(f"[BG] Co-purchase updated ({len(self.heavy.copurchase)} items)")
        except Exception as e:
            print(f"[BG] Co-purchase warning: {e}")

        try:
            u_rows = run_query(bg_http, USER_PROFILE_SQL, timeout=45)
            u_bought: dict[str, set[str]] = {}
            u_top: dict[str, list[str]] = {}
            u_price: dict[str, float] = {}
            for r in u_rows:
                uid = str(r["user_id"])
                bought = {str(x) for x in (r["bought_items"] or []) if x}
                if bought:
                    u_bought[uid] = bought
                if r["top_interacted"]:
                    u_top[uid] = [str(x) for x in r["top_interacted"] if x]
                if r["avg_buy_price"] is not None:
                    val = float(r["avg_buy_price"])
                    if not math.isnan(val) and val > 0:
                        u_price[uid] = val
            self.heavy.user_bought = u_bought
            self.heavy.user_top = u_top
            self.heavy.user_price = u_price
            print(f"[BG] User profiles updated ({len(u_top)} users)")
        except Exception as e:
            print(f"[BG] User profiles warning: {e}")

        try:
            ctx_price: dict[tuple[str, str], tuple[float, float]] = {}
            for r in run_query(bg_http, CONTEXT_PRICE_SQL, timeout=25):
                ctx_price[(str(r["region"]), str(r["device"]))] = (
                    float(r["med_price"]),
                    float(r["iqr_price"]),
                )
            self.heavy.ctx_price = ctx_price
            print(f"[BG] Context prices updated ({len(ctx_price)} segments)")
        except Exception as e:
            print(f"[BG] Context prices warning: {e}")

    def background_worker(self) -> None:
        last_fast = 0.0
        last_heavy = 0.0
        while True:
            now = time.time()

            # 1. SIEMPRE primero el snapshot rápido (catálogo + stock + popularidad)
            if now - last_fast >= 6:
                try:
                    self.fast = self.build_fast_snapshot()
                    last_fast = time.time()
                    if not self.ready.is_set() and self.fast.active_products:
                        self.ready.set()
                        print(f"[BG] Initial fast snapshot ready ({len(self.fast.active_products)} active items)")
                except Exception as e:
                    print(f"[BG] Fast refresh error: {e}")

            # 2. Después los modelos pesados (cada 10 minutos)
            if now - last_heavy >= 600:
                self.refresh_heavy_parts()
                last_heavy = time.time()

            time.sleep(1.0)


def recommend(req: Record, fast: FastSnapshot, heavy: HeavySnapshot) -> list[str]:
    scores: dict[str, float] = defaultdict(float)

    uid = str(req.get("user_id") or "")
    is_new_user = bool(req.get("is_new_user", False))
    ctx = req.get("context") or {}
    page = str(ctx.get("page") or "product")
    region = str(ctx.get("region") or "")
    device = str(ctx.get("device") or "")
    recent_views = req.get("recent_views") or []

    already_bought = heavy.user_bought.get(uid, set()) | fast.live_user_bought.get(uid, set())

    target_price = heavy.user_price.get(uid, 0.0)
    price_spread = 20.0
    if target_price <= 0.0 and (region, device) in heavy.ctx_price:
        target_price, price_spread = heavy.ctx_price[(region, device)]

    subcat_interest: Counter[str] = Counter()

    for cart_pid in fast.live_user_carts.get(uid, []):
        if cart_pid in fast.active_products and cart_pid not in already_bought:
            scores[cart_pid] += 4.5
        for dst, cp_w in heavy.copurchase.get(cart_pid, [])[:10]:
            if dst in fast.active_products and dst not in already_bought:
                scores[dst] += 2.2 * cp_w

    view_ids: list[str] = []
    for item in recent_views:
        pid = item.get("product_id") if isinstance(item, dict) else item
        if pid:
            view_ids.append(str(pid))

    for k, pid in enumerate(reversed(view_ids)):
        decay = 0.75 ** k
        meta = fast.catalog.get(pid)
        if meta:
            subcat_interest[meta["subcategory"]] += decay

        if pid in fast.active_products and pid not in already_bought:
            scores[pid] += 2.4 * decay

        for dst, cp_w in heavy.copurchase.get(pid, []):
            if dst in fast.active_products and dst not in already_bought:
                scores[dst] += 2.9 * cp_w * decay

        for cold_pid, sim_w in fast.cold_neighbors.get(pid, []):
            if cold_pid in fast.active_products and cold_pid not in already_bought:
                scores[cold_pid] += 1.7 * sim_w * decay

    hist_mult = 1.6 if (page == "home" or not view_ids) else 1.0
    if not is_new_user and uid in heavy.user_top:
        for rank, hist_pid in enumerate(heavy.user_top[uid]):
            u_decay = 0.8 ** rank
            meta = fast.catalog.get(hist_pid)
            if meta:
                subcat_interest[meta["subcategory"]] += 0.6 * u_decay * hist_mult
            if hist_pid in fast.active_products and hist_pid not in already_bought and page == "home":
                scores[hist_pid] += 1.3 * u_decay
            for dst, cp_w in heavy.copurchase.get(hist_pid, [])[:10]:
                if dst in fast.active_products and dst not in already_bought:
                    scores[dst] += 1.2 * cp_w * u_decay * hist_mult

    for subcat, weight in subcat_interest.most_common(3):
        for cand in fast.subcat_top.get(subcat, [])[:15]:
            if cand in fast.active_products and cand not in already_bought:
                scores[cand] += 0.9 * weight * (0.4 + fast.pop_score.get(cand, 0.0))

    for pid in list(scores.keys()):
        meta = fast.catalog.get(pid)
        if not meta:
            continue
        if meta["discount"] > 0.05:
            scores[pid] *= (1.0 + 0.6 * meta["discount"])
        if target_price > 0.0 and meta["price"] > 0.0:
            z = abs(meta["price"] - target_price) / max(price_spread, 10.0)
            price_factor = max(0.65, 1.25 - 0.25 * min(z, 2.4))
            scores[pid] *= price_factor

    ranked = [pid for pid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
    result: list[str] = []
    chosen: set[str] = set()

    for pid in ranked:
        if pid in fast.active_products and pid not in chosen:
            result.append(pid)
            chosen.add(pid)
            if len(result) == 10:
                return result

    fallback_pool = fast.pop_rank[:120]
    if target_price > 0.0:
        fallback_pool = sorted(
            fallback_pool,
            key=lambda p: (
                    fast.pop_score.get(p, 0.0)
                    * max(0.6, 1.2 - 0.2 * abs(fast.catalog.get(p, {}).get("price", target_price) - target_price) / max(price_spread, 10.0))
            ),
            reverse=True,
        )

    for pid in fallback_pool:
        if pid in fast.active_products and pid not in chosen and pid not in already_bought:
            result.append(pid)
            chosen.add(pid)
            if len(result) == 10:
                return result

    for pid in fast.pop_rank:
        if pid in fast.active_products and pid not in chosen:
            result.append(pid)
            chosen.add(pid)
            if len(result) == 10:
                return result

    return result


def main() -> None:
    store = ModelStore()
    bg_thread = threading.Thread(target=store.background_worker, daemon=True)
    bg_thread.start()

    print("Waiting for initial catalog & trends snapshot...")
    store.ready.wait(timeout=30)

    seen_set: set[str] = set()
    seen_order: deque[str] = deque(maxlen=20000)

    while True:
        try:
            fast_snap = store.fast
            if not fast_snap.active_products:
                time.sleep(0.5)
                continue

            rows = run_query(hot_http, NEW_REQUESTS_SQL, timeout=3.0)
            fresh = []
            for req in rows:
                rid = req["request_id"]
                if rid not in seen_set:
                    if len(seen_order) == seen_order.maxlen:
                        seen_set.discard(seen_order.popleft())
                    seen_set.add(rid)
                    seen_order.append(rid)
                    fresh.append(req)

            if fresh:
                heavy_snap = store.heavy
                answers = [
                    {
                        "request_id": req["request_id"],
                        "items": recommend(req, fast_snap, heavy_snap),
                        "model_version": MODEL_VERSION,
                    }
                    for req in fresh
                ]
                r = hot_http.post(
                    f"{API}/v1/tables/submissions",
                    params={"database": TEAM},
                    json=answers,
                    timeout=3.0,
                )
                if not r.ok:
                    raise RuntimeError(f"Push HTTP {r.status_code}: {r.text[:300]}")
                print(f"[{MODEL_VERSION}] answered {len(answers)}  PN")
        except Exception as e:
            print(f"[HOT] error: {e}")
            time.sleep(0.5)

        time.sleep(0.15)


if __name__ == "__main__":
    main()