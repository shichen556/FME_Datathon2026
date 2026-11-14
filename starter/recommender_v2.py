"""Recommender v2: session-aware ranking on top of the starter's pull → predict → push loop.

    python starter/recommender_v2.py     # same .env as starter/recommender.py

What the history says (shop.history_sessions, 2M impressions):
- A product the shopper viewed earlier in the session, shown in slot 1, is bought ~17x more often
  than any other product in slot 1 (6.3% vs 0.37%).
- Products bought in the same sessions where a viewed product was viewed (view → purchase
  co-occurrence in shop.history_events) are bought ~7x more often than the rest.
- Slot 1 gets ~2x the purchases of slot 2 and ~9x those of slot 10: the order matters.

So each list is: the session's viewed products (minus ones this shopper already bought), then
products co-purchased with them, then best sellers of the viewed subcategories, then what sells
right now (history + live shop.events). Shoppers without views get the live best sellers.
Everything heavy is computed in RawTree in SQL and refreshed in the background, so answering a
request is pure Python on in-memory dicts (well under 1 ms).

Usage:
    from recommender_v2 import recommend, build_model

    model = build_model()
    items = recommend(viewed_products, model, user_id="u123", k=10)

Tests:
    python -m pytest tests/test_recommender_v2.py -v
"""
from __future__ import annotations

import copy
import logging
import threading
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from recommender import TEAM, Record, out_of_stock, push, query

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

MODEL_VERSION = "v3-Shichen"

# ---------------------------------------------------------------- configuration constants

COVIS_DECAY_FACTOR = 0.8            # exponential weight per view age
COVIS_TOP_N = 30                    # top co-purchases per product
RECENT_WEIGHT_7D = 5                # multiplier for 7-day recent purchases (history)
LIVE_WEIGHT = 20                    # multiplier for live event purchases
LIVE_RECENT_WEIGHT = 40             # multiplier for live + very recent purchases
MAX_PER_SUBCATEGORY = 5             # diversity cap per subcategory per source phase
MAX_COVIS_PER_VIEW = 10             # max co-purchase candidates per viewed product
MAX_SUB_POPULAR = 5                 # popular items to consider per subcategory
REFRESH_INTERVAL = 2                # seconds between light refresh cycles
FULL_REFRESH_INTERVAL = 600         # seconds between full model rebuilds
QUERY_DELAY = 0.5                   # seconds between database queries (rate limit)
REQUEST_BATCH_SIZE = 50             # requests to poll per cycle
REQUEST_POLL_DELAY = 0.3            # seconds between request polls

# ---------------------------------------------------------------- SQL (runs inside RawTree)

COVIS = """
WITH v AS (SELECT DISTINCT toString(session_id) AS s, toString(product_id) AS a FROM {events} WHERE event_type = 'view'{cut}),
     p AS (SELECT DISTINCT toString(session_id) AS s, toString(product_id) AS b FROM {events} WHERE event_type = 'purchase'{cut})
SELECT a, b, count() AS n
FROM v INNER JOIN p ON v.s = p.s
WHERE a != b
GROUP BY a, b ORDER BY n DESC LIMIT {limit} BY a"""
"""For each product a, the N products most often bought in sessions where a was viewed."""

SALES = """
SELECT product_id::String AS product_id,
       countIf(ts::DateTime64(3) >= {recent_from}) AS recent,
       count() AS total
FROM {events}
WHERE event_type = 'purchase'{cut}
GROUP BY product_id"""
"""Purchases per product: all-time and in the most recent window (trend)."""

CATALOG = """
SELECT product_id, argMax(subcategory, v) AS subcategory, argMax(is_active, v) AS is_active
FROM (
    SELECT product_id::String AS product_id, subcategory::String AS subcategory, is_active::Bool AS is_active, '' AS v
    FROM shop.catalog
    UNION ALL
    SELECT product_id::String, subcategory::String, is_active::Bool, toString(ts)
    FROM shop.catalog_updates
)
GROUP BY product_id"""
"""Current catalogue: subcategory and is_active with the latest update applied."""

RECENT_BUYERS = """
SELECT user_id::String AS user_id, product_id::String AS product_id
FROM shop.events
WHERE event_type = 'purchase' AND ts::DateTime64(3) > now() - INTERVAL 6 HOUR
UNION ALL
SELECT r.user_id::String, f.purchased::String
FROM {team}.feedback AS f
INNER JOIN shop.requests AS r ON r.request_id::String = f.request_id::String
WHERE f.purchased::String != '' AND f.ts::DateTime64(3) > now() - INTERVAL 6 HOUR"""
"""Who bought what in the last hours (organic + our carousel): shoppers rarely rebuy."""

NEW_REQUESTS = """
SELECT request_id, user_id, recent_views
FROM shop.requests
ORDER BY ts DESC
LIMIT 50"""


# ---------------------------------------------------------------- model

@dataclass
class Model:
    covis: dict[str, list[tuple[str, float]]] = field(default_factory=dict)  # a -> [(b, weight)], best first
    popular: list[str] = field(default_factory=list)                        # global ranking, best first
    popular_by_sub: dict[str, list[str]] = field(default_factory=dict)      # subcategory -> ranking
    subcategory: dict[str, str] = field(default_factory=dict)               # product -> subcategory
    inactive: set[str] = field(default_factory=set)
    unavailable: set[str] = field(default_factory=set)                       # out of stock right now
    bought: dict[str, set[str]] = field(default_factory=dict)               # user -> products bought lately

    def blocked(self, user: str | None) -> set[str]:
        """Return products to exclude: inactive, out of stock, and previously bought."""
        bought = self.bought.get(user) if user else None
        if bought is None:
            bought = set()
        # Copy bought set to avoid race conditions with the Refresher thread
        return self.inactive | self.unavailable | set(bought)


def load_covis(cut: str = "", live: bool = True) -> dict[str, list[tuple[str, float]]]:
    sources = ["shop.history_events"] + (["shop.events"] if live else [])
    counts: Counter[tuple[str, str]] = Counter()
    for events in sources:
        for r in query(COVIS.format(events=events, cut=cut, limit=COVIS_TOP_N)):
            counts[r["a"], r["b"]] += int(r["n"])
    covis: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (a, b), n in counts.items():
        covis[a].append((b, n))
    out: dict[str, list[tuple[str, float]]] = {}
    for a, lst in covis.items():
        lst.sort(key=lambda x: -x[1])
        top = lst[0][1]
        out[a] = [(b, n / top) for b, n in lst[:COVIS_TOP_N]]  # normalised: best co-purchase = 1
    return out


def load_popularity(cut: str = "", live: bool = True, until: str | None = None) -> Counter[str]:
    """Score = all-time purchases + RECENT_WEIGHT_7x recent purchases + LIVE_WEIGHT live."""
    score: Counter[str] = Counter()
    recent_from = f"toDateTime64('{until}', 3) - INTERVAL 7 DAY" if until else \
        "(SELECT max(ts::DateTime64(3)) FROM shop.history_events) - INTERVAL 7 DAY"
    for r in query(SALES.format(events="shop.history_events", cut=cut, recent_from=recent_from)):
        score[r["product_id"]] += int(r["total"]) + RECENT_WEIGHT_7D * int(r["recent"])
    if live:
        for r in query(SALES.format(events="shop.events", cut="", recent_from="now() - INTERVAL 3 HOUR")):
            score[r["product_id"]] += LIVE_WEIGHT * int(r["total"]) + LIVE_RECENT_WEIGHT * int(r["recent"])
    return score


def build_model(cut_date: str | None = None, live: bool = True) -> Model:
    """cut_date ('YYYY-MM-DD') restricts history for offline evaluation; live adds shop.events."""
    cut = f" AND ts::DateTime64(3) < '{cut_date}'" if cut_date else ""
    m = Model()
    for r in query(CATALOG):
        m.subcategory[r["product_id"]] = r["subcategory"]
        if not r["is_active"]:
            m.inactive.add(r["product_id"])
    m.covis = load_covis(cut, live)
    score = load_popularity(cut, live, cut_date)
    for p in m.subcategory:
        score.setdefault(p, 0)
    m.popular = [p for p, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))]
    by_sub: dict[str, list[str]] = defaultdict(list)
    for p in m.popular:
        by_sub[m.subcategory.get(p, "")].append(p)
    m.popular_by_sub = dict(by_sub)
    return m


# ---------------------------------------------------------------- ranking

def recommend(recent_views: list[Record] | None, model: Model, user: str | None = None, k: int = 10) -> list[str]:
    """Generate k product recommendations with diversity limits per source phase.

    Strategy:
    1. Viewed products (most viewed first, then most recent), excluding already bought
    2. Co-purchased with viewed products (exponential decay for older views), capped per sub
    3. Best sellers of viewed subcategories (max {MAX_PER_SUBCATEGORY} per sub)
    4. Global popular items (catch-all), capped per sub for diversity

    Each phase respects diversity limits to avoid over-representing any subcategory.
    """
    blocked = model.blocked(user)
    views = [v["product_id"] for v in (recent_views or [])]

    # Phase 0: filter out already-bought from views (avoid bloating phase 1)
    bought_ids = blocked & set(views)
    if bought_ids:
        views = [v for v in views if v not in bought_ids]

    out: list[str] = []
    sub_counts: Counter[str] = Counter()  # track subcategory counts across all phases

    def add(p: str) -> bool:
        if p not in blocked and p not in out:
            out.append(p)
            sub = model.subcategory.get(p, "")
            if sub:
                sub_counts[sub] += 1
        return len(out) >= k

    # 1. Products viewed in this session: most viewed first, then most recent
    view_count = Counter(views)
    last_seen = {p: i for i, p in enumerate(views)}
    viewed_sorted = sorted(view_count, key=lambda p: (-view_count[p], -last_seen[p]))
    for p in viewed_sorted[:k]:  # Cap: at most k viewed products
        if add(p):
            break

    if len(out) < k:
        # 2. Co-purchased with the viewed products, recent views weigh more
        # Exponential decay: recent views (reversed list) get higher weight
        score: Counter[str] = Counter()
        for age, p in enumerate(reversed(views)):
            for b, w in model.covis.get(p, []):
                score[b] += w * (COVIS_DECAY_FACTOR ** age)
        viewed_set = set(viewed_sorted)  # exclude products already in phase 1
        co_purchased = [p for p, _ in score.most_common() if p not in viewed_set]
        for p in co_purchased:
            # Diversity cap: max MAX_COVIS_PER_VIEW per subcategory from co-purchases
            sub = model.subcategory.get(p, "")
            if sub and sub_counts.get(sub, 0) >= MAX_PER_SUBCATEGORY:
                continue
            if add(p):
                break

    if len(out) < k:
        # 3. Best sellers of the viewed subcategories (max MAX_SUB_POPULAR per sub)
        subs = list(dict.fromkeys(model.subcategory.get(p) for p in reversed(views) if model.subcategory.get(p)))
        for sub in subs:
            for p in model.popular_by_sub.get(sub, [])[:MAX_SUB_POPULAR]:
                if add(p):
                    break
            if len(out) >= k:
                break

    if len(out) < k:
        # 4. Global popular items (catch-all, exclude viewed products + diversity cap)
        viewed_set = set(viewed_sorted)
        for p in model.popular:
            if p in viewed_set:
                continue
            # Diversity cap: max MAX_PER_SUBCATEGORY per subcategory globally
            sub = model.subcategory.get(p, "")
            if sub and sub_counts.get(sub, 0) >= MAX_PER_SUBCATEGORY:
                continue
            if add(p):
                break

    return out


# ---------------------------------------------------------------- live loop

class Refresher(threading.Thread):
    """Rebuilds the slow parts in the background so the answer loop never waits for them."""

    def __init__(self, model: Model):
        super().__init__(daemon=True)
        self.model = model

    def _copy_model_state(self, src: Model, dst: Model) -> None:
        """Safely deep-copy mutable model fields from src to dst."""
        dst.covis = copy.deepcopy(src.covis)
        dst.popular = list(src.popular)
        dst.popular_by_sub = {k: list(v) for k, v in src.popular_by_sub.items()}
        dst.subcategory = dict(src.subcategory)
        dst.inactive = set(src.inactive)

    def run(self) -> None:
        last_full = time.time()
        while True:
            try:
                # Update stock status every REFRESH_INTERVAL seconds
                time.sleep(QUERY_DELAY)  # rate limit between queries
                self.model.unavailable = out_of_stock()

                # Update recent buyers every REFRESH_INTERVAL seconds
                time.sleep(QUERY_DELAY)  # rate limit between queries
                bought: dict[str, set[str]] = {}
                for r in query(RECENT_BUYERS.format(team=TEAM)):
                    user_id = r["user_id"]
                    if user_id not in bought:
                        bought[user_id] = set()
                    bought[user_id].add(r["product_id"])
                self.model.bought = bought

                # Full model rebuild every FULL_REFRESH_INTERVAL seconds
                if time.time() - last_full > FULL_REFRESH_INTERVAL:
                    fresh = build_model()
                    # Preserve live-updated state (keep these from the old model)
                    fresh.unavailable = self.model.unavailable
                    fresh.bought = self.model.bought
                    # Safely deep-copy model state
                    self._copy_model_state(fresh, self.model)
                    last_full = time.time()
                    logger.info("model refreshed: %d products with covis, %d inactive",
                                len(self.model.covis), len(self.model.inactive))
            except Exception as e:
                logger.error("refresh failed (keeping the last model): %s\n%s", e, traceback.format_exc())
            time.sleep(REFRESH_INTERVAL)


def main() -> None:
    model = build_model()
    model.unavailable = out_of_stock()
    logger.info("model ready: %d products with co-purchases, %d inactive", len(model.covis), len(model.inactive))
    Refresher(model).start()
    seen: set[str] = set()
    request_count = 0
    while True:
        try:
            fresh = [r for r in query(NEW_REQUESTS) if r["request_id"] not in seen]
            if fresh:
                answers = []
                for r in fresh:
                    seen.add(r["request_id"])
                    answers.append({"request_id": r["request_id"],
                                    "items": recommend(r.get("recent_views"), model, r.get("user_id")),
                                    "model_version": MODEL_VERSION})
                    request_count += 1
                push(answers)
                if request_count % 100 == 0:
                    logger.info("answered %d requests total", request_count)
        except Exception as e:  # keep running: shoppers keep arriving while you sleep
            logger.error("main loop error: %s\n%s", e, traceback.format_exc())
            time.sleep(1)
        time.sleep(0.3)


if __name__ == "__main__":
    main()
