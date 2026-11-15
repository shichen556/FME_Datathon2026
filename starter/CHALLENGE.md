# RawTree Challenge · Real-Time Recommendation

**Datathon FME 2026 · 14–15 November 2026 · UPC Barcelona** · [Challenge page](https://datathon.rawtree.dev) · [Leaderboard](https://datathon.rawtree.dev/leaderboard)

> Shoppers arrive at an online store every few seconds. For each one you have **3 seconds** to choose the **10 products** they will see. A hidden model simulates each shopper's decision to click and buy. Practise against the live stream on Saturday with a public leaderboard; from **Sunday 10:00 to 12:00 CET (UTC+1)** the stream switches to data nobody has seen and the leaderboard goes dark. At 12:00 the final ranking appears on its own.

---

## The story

An online store sells around 5,000 products in ten categories. On the home page and on every product page there is a row of ten recommended products. Right now that row just shows the **all-time best sellers**. You have to build something that sells more, and it will be tested live, on shoppers arriving in real time.

## What you build

A system that, on its own and without anyone pressing buttons:

1. **Reads recommendation requests** from a RawTree table as they arrive. Each request describes a shopper and what they have just done in this session.
2. **Within 3 seconds, writes back an ordered list of 10 product IDs** for that request.
3. **Learns** from the feedback it receives (what was clicked and bought) and from the shared stream of store activity.

```
             ┌──────────────────────────────┐
             │  Shopper simulator (hidden)  │
             └──────┬────────────────▲──────┘
  shop.requests     │                │ reads your answers,
  shop.events       │                │ decides clicks & purchases
  shop.catalog_...  ▼                │
             ┌─────────────┐   ┌─────┴──────────────────┐
             │ Your system │──▶│ team_NN.submissions    │
             └──────▲──────┘   └────────────────────────┘
                    │          ┌────────────────────────┐
                    └──────────│ team_NN.feedback       │ only your team can read it
                               └────────────────────────┘
```

## Data

All data lives in **RawTree**. Each team gets one API key that can **read** the shared `shop` database and **read and write** its own database `team_NN`.

### Available from the start

**`shop.catalog`**: the product catalogue, around 5,000 products.

| Field | Type | Notes |
|---|---|---|
| `product_id` | string | Opaque ID |
| `category` | string | Top-level category (10 values) |
| `subcategory` | string | 90 values |
| `brand` | string | |
| `price_eur` | number | Price at the start. Price changes arrive in `shop.catalog_updates` |
| `description` | string | One or two sentences of product text |
| `created_at` | timestamp | |
| `is_active` | bool | |

**`shop.history_sessions`**: 60 days of past carousel impressions (≈2 million records), served by the old system.

| Field | Type | Notes |
|---|---|---|
| `request_id` | string | |
| `ts` | timestamp | |
| `user_id` | string | Opaque ID |
| `context` | object | `device` (web, ios, android), `region`, `page` (home, product, category) |
| `recent_views` | array | Products viewed earlier in the session, with timestamps |
| `shown` | array | The 10 products the old system showed, in order |
| `propensity` | array | Probability the old system had of showing each of those products in that slot, given the products in the slots above it |
| `clicked` | string or null | Product clicked, if any |
| `purchased` | string or null | Product bought, if any |
| `revenue_eur` | number | |

The old system is a "best sellers plus a bit of randomness" carousel, so this log is **biased towards popular products**. The `propensity` column lets you correct for that bias, if you want to.

**`shop.history_events`**: 60 days of organic store activity that did **not** come from the carousel (`view`, `add_to_cart`, `purchase`), ≈12 million records. Useful to learn what users like beyond what the old system showed them.

| Field | Type | Notes |
|---|---|---|
| `ts` | timestamp | |
| `event_type` | string | `view`, `add_to_cart`, `purchase` |
| `user_id`, `session_id` | string | |
| `product_id` | string | |
| `price_eur` | number | Price at the time of the event |
| `device`, `region` | string | |

### During the event (Saturday to Sunday)

**`shop.requests`** (append-only): one record per shopper arriving at the carousel, about **3 per second**, day and night.

```json
{
  "request_id": "r_01JD8K3...",
  "ts": "2026-11-14T16:02:11.482Z",
  "user_id": "u_7f21c9",
  "is_new_user": false,
  "context": {"device": "ios", "region": "Catalunya", "page": "product"},
  "recent_views": [
    {"product_id": "p_5a1e", "ts": "2026-11-14T16:01:40Z"},
    {"product_id": "p_0b9d", "ts": "2026-11-14T16:01:58Z"}
  ]
}
```

**`shop.events`** (append-only): organic store activity in real time, same format as `shop.history_events`. This is where you can spot trends as they happen.

**`shop.catalog_updates`** (append-only): one record per change, with the full product after the change plus `ts` and `change` (`new_product`, `price_change`, `out_of_stock`, `back_in_stock`). The current catalogue is `shop.catalog` with the latest update of each product applied on top.

**`team_NN.feedback`** (only your team can read it): what happened with each of your recommendations, written a few seconds after the deadline.

```json
{
  "request_id": "r_01JD8K3...",
  "ts": "2026-11-14T16:02:16.900Z",
  "shown": ["p_91aa", "p_5a1e", "..."],
  "served_by": "team",
  "fallback_reason": "",
  "latency_ms": 840,
  "clicked": "p_91aa",
  "purchased": "p_91aa",
  "revenue_eur": 34.99
}
```

`served_by` is `team` if your answer arrived on time and was valid, and `fallback` if not; in that case the shopper saw the baseline (the all-time best sellers that are in stock) and `fallback_reason` says why (`missing`, `late` or `invalid`). `clicked` and `purchased` are `""` when nothing happened. The first record of the table (`request_id = "__init__"`) is a placeholder: ignore it.

**`team_NN.scratch`**: an empty table for whatever you want to store in RawTree (features, embeddings, model outputs). No schema needed: insert JSON.

## What you submit

Insert **one record per request** into **`team_NN.submissions`**:

```json
{
  "request_id": "r_01JD8K3...",
  "items": ["p_91aa", "p_5a1e", "p_c302", "p_77d0", "p_0e12",
            "p_a4b8", "p_19f3", "p_6d2c", "p_e801", "p_3b5a"],
  "model_version": "v3-mf-bandit"
}
```

Rules:

- **Exactly 10 distinct, active product IDs.** Invalid answers are replaced by the fallback.
- The answer must reach RawTree **within 3 seconds of the request `ts`**, as measured by the organisers' clock (polled every half second). Late answers are replaced by the fallback.
- If you send several answers for the same request, only one counts: send one.
- **Batch your inserts** (for example, every half second) instead of one HTTP call per request. For reference, the starter baseline polls every 0.3 s and answers in about 1 s (95% within 1.5 s) from the request `ts`: the rest of the 3 seconds is yours to compute.
- Order matters: shoppers look at the first slots much more than at the last ones.

## Timeline

| When | What |
|---|---|
| **Saturday, opening** | Data, keys and starter kit released |
| **Saturday 10:00 → Sunday 10:00** | Practice round: live stream, **public leaderboard** updated every 10 minutes |
| **Sunday 10:00 → 12:00** | **Final round**: the stream switches to **new data** (new shoppers, new products, new trends). The leaderboard is hidden |
| **Sunday 12:00** | Submissions close. The stream stops and the **final ranking appears automatically** on the leaderboard page |

All times are Barcelona time (CET, UTC+1); the data timestamps are UTC.

There is no file to upload and nothing to do at 12:00. **Your system *is* your submission**: whatever it answers between 10:00 and 12:00 is what gets scored.

During the final round nothing changes on your side: your system keeps reading requests and answering them, the requests are simply new. You keep receiving feedback, so you can estimate your own conversion, but you will not see anyone else's until 12:00. **Make sure your best version is running by 10:00.**

**Status light.** During the final round the leaderboard shows only a green or red light per team: green if more than 90% of your answers in the last 5 minutes were valid and on time. It does not score anything; it is there so that if your system breaks at 10:05, you notice.

**Shoppers keep arriving while you sleep.** A request that is not answered gets the fallback.

Leaderboard: **https://datathon.rawtree.dev/leaderboard**

## Evaluation

### 70 points · Final round (automatic)

Computed only on the requests of the final round (Sunday 10:00–12:00 CET). The practice round does not count.

| Component | Points | Metric |
|---|---|---|
| Conversion | 50 | Expected purchases per 100 requests (see *No luck* below) |
| Cold start | 10 | The same, restricted to **cold requests**: a new shopper (`is_new_user`), or `recent_views` that include a product added during the event (`new_product` in `shop.catalog_updates`) |
| Reliability | 10 | Share of requests answered validly and on time |

Conversion and cold start are turned into a 0–100 score between two anchors the organisers compute on the same stream:

```
score = 100 × (team − baseline) / (oracle − baseline), clipped to [0, 100]
```

- **baseline** (0): the all-time best sellers that are in stock, ranked once at the start of the stream (the starter-kit recommender). It is also the fallback.
- **oracle** (100): the best list possible, the 10 products the hidden model itself would pick for each shopper.
- The leaderboard also shows a **reference**: a strong recommender built by the organisers, as a benchmark. **It can be beaten.**

Reliability is the percentage of requests answered validly and on time.

**On the leaderboard** the 70 points are normalised to a score out of 100 (about 71 conversion, 14 cold start, 14 reliability). Your final grade is 70 % of that score plus the jury's 30 points.

**No luck.** Whether a shopper buys is random. To keep luck out of the ranking, the score uses each shopper's *probability* of buying, given the 10 products you showed, as computed by the simulator's hidden model, instead of the coin flip. Your feedback shows the realised clicks and purchases; over many requests the two agree, so maximise real purchases and the score follows. And real purchases still feed the model a little: a shopper who already bought a product tends not to want it again, so what your system sells changes later scores.

### 30 points · Presentation (jury)

On Sunday afternoon each team gives a **short presentation with a demo** to the jury. The top teams share their repository, so keep it readable.

| Criterion | Points | What we look at |
|---|---|---|
| Method | 10 | Is the approach sound and well justified? How was it validated offline before going live? |
| Learning from the stream | 10 | How did the system use feedback and live events (exploration, trends, price changes, cold start)? |
| Use of RawTree | 5 | Features computed in SQL, embeddings, how the pipeline reads and writes |
| Communication | 5 | Could a product manager understand what the system does and why it works? |

**Tie-breaker:** expected revenue per request in the final round.

## Getting started

1. **Get your credentials** at the RawTree stand when you register your team: a `TEAM_ID` (like `team_07`) and a `RAWTREE_API_KEY`. Copy `.env.example` to `.env` and fill them in.
2. **Meet RawTree.** It is an analytics database for JSON: you insert JSON and query it with SQL, no schema needed. It was built to be used by agents, so let yours find its way:
   - Docs for agents: <https://rawtree.com/llms.txt>
   - API: `https://api.rawtree.com` (`POST /v1/query`, `POST /v1/tables/{table}?database=team_NN`), auth with `Authorization: Bearer $RAWTREE_API_KEY`
   - CLI: `curl -fsSL https://rawtree.com/install.sh | bash`, then `rtree query --api-key $RAWTREE_API_KEY --database $TEAM_ID "SELECT count() FROM shop.requests"`
   - MCP: `https://mcp.rawtree.com/mcp`, sending your key as an `Authorization: Bearer` header

   Tables are schemaless: every column is `Dynamic`, each value keeps its own type. Filters and most functions just work; join keys and a few aggregates need a cast, like `product_id::String`.
3. **Get on the leaderboard in 30 minutes:** run the baseline.

   ```bash
   pip install -r starter/requirements.txt
   python starter/recommender.py
   ```

   Or, without installing anything globally:

   ```bash
   uv run --with requests python starter/recommender.py
   ```

   The live stream opens on **Saturday at 10:00 CET**. Until then `shop.requests`, `shop.events` and `shop.catalog_updates` are empty, so queries on them fail with *Unknown expression identifier* and the baseline just retries. Explore the history meanwhile.

4. **Beat it.** Explore the history, evaluate ideas offline (`starter/offline_eval.ipynb`), deploy, read your feedback, repeat.

## Starter kit

| File | What it is |
|---|---|
| `starter/recommender.py` | The baseline, about 120 lines, as a `pull → predict → push` loop: `recommend()` is the part to replace |
| `starter/queries.sql` | SQL examples: current catalogue, popularity per category in the last hour, co-views, reading your feedback, your on-time rate |
| `starter/offline_eval.ipynb` | Offline evaluation on `shop.history_sessions` — imports `recommender.py`, so it tests the same code that runs live; includes an inverse-propensity estimate of a new policy's click rate |

To open the notebook without installing anything globally:

```bash
pipx run $(sed 's/^/--with /' starter/requirements.txt | tr '\n' ' ') jupyter notebook starter/offline_eval.ipynb
```

## Rules

- All shoppers, sessions and outcomes are generated by a simulator with a secret seed. The catalogue is synthetic; no public dataset is used for scoring.
- Feedback is private to each team. **Do not share keys.**
- Recommendations must be produced by code, not by hand. The top teams share their repository with the jury.
- Your system has to run unattended: keep it running on a machine that will not go to sleep.
- Anything a team cannot explain in the presentation may be penalised.

Questions? Find the RawTree team at the stand. Good luck!
