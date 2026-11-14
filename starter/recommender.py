
"""
V3 Hybrid Recommendation System

Run:
    python starter/recommender.py

Environment:
    TEAM_ID
    RAWTREE_API_KEY
    RAWTREE_API_URL (optional)

Workflow:
    Load data -> Pull -> Predict -> Buffer -> Push

Submissions are batched every 0.5 seconds.
"""

from __future__ import annotations

import os
import time
import math
from pathlib import Path
from typing import Any

import requests


# ==================================================
# CONFIGURATION
# ==================================================

for line in Path(".env").read_text().splitlines() if Path(".env").exists() else []:
    key, _, value = line.partition("=")
    os.environ.setdefault(key.strip(), value.strip())

API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com")
TEAM = os.environ["TEAM_ID"]

http = requests.Session()
http.headers["Authorization"] = (
    f"Bearer {os.environ['RAWTREE_API_KEY']}"
)

Record = dict[str, Any]

BATCH_INTERVAL = 0.5
POLL_INTERVAL = 0.1

CATALOG_REFRESH = 300
STATS_REFRESH = 300
STOCK_REFRESH = 1


# ==================================================
# SQL QUERIES
# ==================================================

NEW_REQUESTS = """
SELECT
    request_id,
    ts,
    user_id,
    is_new_user,
    context,
    recent_views
FROM shop.requests
ORDER BY ts DESC
LIMIT 50
"""

PRODUCT_STATS = """
SELECT
    product_id,
    countIf(event_type = 'view') AS views,
    countIf(event_type = 'add_to_cart') AS carts,
    countIf(event_type = 'purchase') AS purchases
FROM shop.history_events
GROUP BY product_id
"""

CATALOG = """
SELECT
    product_id,
    category,
    subcategory,
    brand,
    price_eur,
    is_active
FROM shop.catalog
"""

OUT_OF_STOCK = """
SELECT product_id::String AS product_id
FROM shop.catalog_updates
WHERE change::String IN ('out_of_stock', 'back_in_stock')
GROUP BY product_id
HAVING argMax(change::String, ts::DateTime64(3)) = 'out_of_stock'
"""


# ==================================================
# API HELPERS
# ==================================================

def query(sql: str) -> list[Record]:
    response = http.post(
        f"{API}/v1/query",
        json={"sql": sql},
        timeout=30
    )

    response.raise_for_status()

    return response.json()["data"]


# ==================================================
# DATA LOADING
# ==================================================

def load_catalog() -> dict[str, Record]:
    """Load active products."""

    rows = query(CATALOG)

    return {
        row["product_id"]: row
        for row in rows
        if row.get("is_active") is True
    }


def load_product_stats() -> dict[str, Record]:
    """Load historical product interaction statistics."""

    rows = query(PRODUCT_STATS)

    return {
        row["product_id"]: {
            "views": int(row["views"]),
            "carts": int(row["carts"]),
            "purchases": int(row["purchases"])
        }
        for row in rows
    }


def out_of_stock() -> set[str]:
    """Return products currently out of stock."""

    return {
        row["product_id"]
        for row in query(OUT_OF_STOCK)
    }


# ==================================================
# SCORING HELPERS
# ==================================================

def normalize(value: float, maximum: float) -> float:
    """Normalize interaction counts between 0 and 1."""

    if maximum <= 0:
        return 0.0

    return math.log1p(value) / math.log1p(maximum)


# ==================================================
# PULL
# ==================================================

def pull(seen: set[str]) -> list[Record]:
    """Retrieve requests not previously processed."""

    fresh = []

    for req in query(NEW_REQUESTS):

        request_id = req["request_id"]

        if request_id not in seen:
            seen.add(request_id)
            fresh.append(req)

    return fresh


# ==================================================
# RECOMMEND
# ==================================================

def recommend(
    recent_views: list[Record],
    catalog: dict[str, Record],
    stats: dict[str, Record],
    unavailable: set[str],
    limit: int = 10
) -> list[str]:
    """Hybrid recommendation scoring."""

    # Products already viewed in the current session
    viewed_ids = {
        view["product_id"]
        for view in recent_views
    }

    # Extract shopper preferences
    preferred_categories = set()
    preferred_subcategories = set()
    preferred_brands = set()

    for view in recent_views:

        product = catalog.get(view["product_id"])

        if not product:
            continue

        if product.get("category"):
            preferred_categories.add(product["category"])

        if product.get("subcategory"):
            preferred_subcategories.add(product["subcategory"])

        if product.get("brand"):
            preferred_brands.add(product["brand"])

    # Global normalization values
    max_views = max(
        (s["views"] for s in stats.values()),
        default=0
    )

    max_carts = max(
        (s["carts"] for s in stats.values()),
        default=0
    )

    max_purchases = max(
        (s["purchases"] for s in stats.values()),
        default=0
    )

    scored_products = []

    for product_id, product in catalog.items():

        # Availability filters
        if product_id in unavailable:
            continue

        if product_id in viewed_ids:
            continue

        product_stats = stats.get(
            product_id,
            {
                "views": 0,
                "carts": 0,
                "purchases": 0
            }
        )

        # Historical interaction scores
        purchase_score = normalize(
            product_stats["purchases"],
            max_purchases
        )

        cart_score = normalize(
            product_stats["carts"],
            max_carts
        )

        view_score = normalize(
            product_stats["views"],
            max_views
        )

        # Personalization scores
        category_score = float(
            product.get("category") in preferred_categories
        )

        subcategory_score = float(
            product.get("subcategory") in preferred_subcategories
        )

        brand_score = float(
            product.get("brand") in preferred_brands
        )

        # Weighted hybrid score
        score = (
            0.25 * purchase_score
            + 0.25 * cart_score
            + 0.20 * category_score
            + 0.15 * subcategory_score
            + 0.05 * brand_score
            + 0.10 * view_score
        )

        scored_products.append((score, product_id))

    # Highest score first
    scored_products.sort(reverse=True)

    recommendations = []
    category_counts = {}

    # First pass: maximum 3 products per category
    for score, product_id in scored_products:

        category = catalog[product_id].get("category")

        if category_counts.get(category, 0) >= 3:
            continue

        recommendations.append(product_id)

        category_counts[category] = (
            category_counts.get(category, 0) + 1
        )

        if len(recommendations) == limit:
            break

    # Second pass: fill remaining positions
    if len(recommendations) < limit:

        already_selected = set(recommendations)

        for score, product_id in scored_products:

            if product_id in already_selected:
                continue

            recommendations.append(product_id)

            if len(recommendations) == limit:
                break

    return recommendations


# ==================================================
# PREDICT
# ==================================================

def predict(
    requests: list[Record],
    catalog: dict[str, Record],
    stats: dict[str, Record],
    unavailable: set[str]
) -> list[Record]:
    """Generate exactly one answer per request."""

    answers = []

    for req in requests:

        items = recommend(
            req.get("recent_views") or [],
            catalog,
            stats,
            unavailable
        )

        answers.append({
            "request_id": req["request_id"],
            "items": items,
            "model_version": "v2-ruben"
        })

    return answers


# ==================================================
# PUSH
# ==================================================

def push(answers: list[Record]) -> None:
    """Batch insert into team_NN.submissions."""

    if not answers:
        return

    response = http.post(
        f"{API}/v1/tables/submissions",
        params={"database": TEAM},
        json=answers,
        timeout=10
    )

    response.raise_for_status()

    print(f"Successfully submitted {len(answers)} answers")


# ==================================================
# MAIN LOOP
# ==================================================

def main() -> None:

    print("Starting V3 Hybrid Recommender...")

    # Load initial data
    catalog = load_catalog()
    stats = load_product_stats()

    print(f"Loaded {len(catalog)} active products")
    print(f"Loaded {len(stats)} product statistics")

    # Runtime state
    seen: set[str] = set()
    pending_answers: list[Record] = []

    unavailable: set[str] = set()

    stock_checked = 0.0
    last_push = time.monotonic()

    last_catalog_refresh = time.monotonic()
    last_stats_refresh = time.monotonic()

    while True:

        try:

            now = time.monotonic()

            # --------------------------------------
            # Refresh stock
            # --------------------------------------

            if now - stock_checked >= STOCK_REFRESH:

                try:
                    unavailable = out_of_stock()
                    stock_checked = time.monotonic()

                except Exception as e:
                    print(f"Stock refresh failed: {e}")

            # --------------------------------------
            # Refresh catalogue
            # --------------------------------------

            if now - last_catalog_refresh >= CATALOG_REFRESH:

                try:
                    catalog = load_catalog()
                    last_catalog_refresh = time.monotonic()

                    print("Catalogue refreshed")

                except Exception as e:
                    print(f"Catalogue refresh failed: {e}")

            # --------------------------------------
            # Refresh product statistics
            # --------------------------------------

            if now - last_stats_refresh >= STATS_REFRESH:

                try:
                    stats = load_product_stats()
                    last_stats_refresh = time.monotonic()

                    print("Product statistics refreshed")

                except Exception as e:
                    print(f"Statistics refresh failed: {e}")

            # --------------------------------------
            # PULL
            # --------------------------------------

            new_requests = pull(seen)

            # --------------------------------------
            # PREDICT
            # --------------------------------------

            answers = predict(
                new_requests,
                catalog,
                stats,
                unavailable
            )

            # --------------------------------------
            # BUFFER
            # --------------------------------------

            pending_answers.extend(answers)

            # --------------------------------------
            # PUSH EVERY 0.5 SECONDS
            # --------------------------------------

            if (
                pending_answers
                and time.monotonic() - last_push >= BATCH_INTERVAL
            ):

                batch = pending_answers.copy()

                push(batch)

                # Clear only after successful submission
                del pending_answers[:len(batch)]

                last_push = time.monotonic()

        except Exception as e:

            print(f"Main loop error: {e}")

        time.sleep(POLL_INTERVAL)


# ==================================================
# ENTRY POINT
# ==================================================

if __name__ == "__main__":
    main()
