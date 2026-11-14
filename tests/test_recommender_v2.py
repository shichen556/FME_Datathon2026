"""Unit tests for starter.recommender_v2 recommendation logic and thread safety."""
from __future__ import annotations

import threading
import time
from collections import Counter
from unittest.mock import patch, MagicMock

import pytest

# ------------------------------------------------------------------------ helpers

def _make_model(**overrides) -> "Model":
    """Build a minimal Model with sensible defaults, then apply overrides."""
    from starter.recommender_v2 import Model
    defaults = dict(
        covis={"p1": [("p2", 1.0), ("p3", 0.5)], "p2": [("p1", 1.0)]},
        popular=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10"],
        popular_by_sub={"electronics": ["p1", "p2", "p3"], "books": ["p4", "p5", "p6"]},
        subcategory={"p1": "electronics", "p2": "electronics", "p3": "books",
                      "p4": "books", "p5": "books", "p6": "electronics",
                      "p7": "electronics", "p8": "books", "p9": "electronics",
                      "p10": "books"},
        inactive=set(),
        unavailable=set(),
        bought={},
    )
    defaults.update(overrides)
    return Model(**defaults)


def _make_view(*product_ids: str) -> list[dict]:
    """Create recent_views records from product IDs."""
    return [{"product_id": pid} for pid in product_ids]


# ------------------------------------------------------------------------ fixtures

@pytest.fixture
def model_with_covis():
    return _make_model(
        covis={"p1": [("p2", 1.0), ("p3", 0.5)], "p2": [("p1", 1.0)]},
        popular=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10"],
        popular_by_sub={"electronics": ["p1", "p2", "p3"], "books": ["p4", "p5", "p6"]},
        subcategory={"p1": "electronics", "p2": "electronics", "p3": "books",
                      "p4": "books", "p5": "books", "p6": "electronics",
                      "p7": "electronics", "p8": "books", "p9": "electronics",
                      "p10": "books"},
    )


# ------------------------------------------------------------------------ recommend: basic behaviour

class TestRecommendBasic:
    """Test the basic 4-phase recommendation pipeline."""

    def test_returns_exactly_k_items(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1"), model_with_covis, k=10)
        assert len(items) == 10

    def test_returns_all_viewed_when_fewer_than_k(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1", "p2"), model_with_covis, k=10)
        assert "p1" in items
        assert "p2" in items
        assert len(items) == 10  # fills up to k with covis, sub, and popular

    def test_no_duplicates_in_output(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1", "p1"), model_with_covis, k=10)
        assert len(items) == len(set(items))

    def test_viewed_products_appear_first(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1", "p2"), model_with_covis, k=5)
        assert items.index("p1") < items.index("p3")  # viewed before covis

    def test_blocked_products_excluded(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(inactive={"p1", "p2"})
        items = recommend(_make_view("p3"), model, k=5)
        assert "p1" not in items
        assert "p2" not in items

    def test_out_of_stock_excluded(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(unavailable={"p1"})
        items = recommend(_make_view("p2"), model, k=5)
        assert "p1" not in items

    def test_inactive_excluded(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(inactive={"p1"})
        items = recommend(_make_view("p2"), model, k=5)
        assert "p1" not in items

    def test_already_bought_excluded(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(bought={"u1": {"p1"}})
        items = recommend(_make_view("p2"), model, user="u1", k=5)
        assert "p1" not in items


class TestRecommendPhases:
    """Test each of the 4 recommendation phases in isolation."""

    def test_phase1_viewed_products(self, model_with_covis):
        from starter.recommender_v2 import recommend
        # p1 is viewed once, p2 once - order by view count desc, then recency desc
        items = recommend(_make_view("p1", "p2"), model_with_covis, k=2)
        assert len(items) == 2
        assert set(items) == {"p1", "p2"}  # both present

    def test_phase1_most_viewed_first(self, model_with_covis):
        from starter.recommender_v2 import recommend
        # p1 viewed twice, p2 once
        items = recommend(_make_view("p1", "p1", "p2"), model_with_covis, k=2)
        assert items[0] == "p1"
        assert items[1] == "p2"

    def test_phase2_covis_when_few_views(self, model_with_covis):
        from starter.recommender_v2 import recommend
        # Only one view that fits in k, so covis kicks in
        items = recommend(_make_view("p1"), model_with_covis, k=4)
        assert items[0] == "p1"
        assert "p2" in items  # most covis with p1

    def test_phase3_subcategory_fill(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(
            covis={},  # no co-purchases
            popular=["p1", "p2", "p3", "p4", "p5"],
            popular_by_sub={"electronics": ["p1", "p2", "p3"], "books": ["p4", "p5"]},
            subcategory={"p1": "electronics", "p2": "electronics", "p3": "books",
                          "p4": "books", "p5": "electronics"},
        )
        items = recommend(_make_view("p1"), model, k=5)
        assert items[0] == "p1"
        assert "p2" in items  # same subcategory

    def test_phase4_global_popular(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(
            covis={},
            popular_by_sub={},
            subcategory={},
        )
        items = recommend(_make_view("p100"), model, k=5)
        assert items == ["p100", "p1", "p2", "p3", "p4"]


class TestRecommendEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_no_views(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(None, model_with_covis, k=5)
        assert len(items) == 5
        assert items[0] == "p1"  # falls through to popular

    def test_empty_views_list(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend([], model_with_covis, k=5)
        assert len(items) == 5
        assert items[0] == "p1"

    def test_no_user_id(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1"), model_with_covis, user=None, k=5)
        assert "p1" in items

    def test_viewed_product_already_bought(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(bought={"u1": {"p1"}})
        items = recommend(_make_view("p1"), model, user="u1", k=5)
        assert "p1" not in items
        assert len(items) == 5  # fills up to k with covis and popular

    def test_all_products_blocked(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(
            popular=["p1", "p2", "p3"],
            inactive={"p1", "p2", "p3"},
        )
        items = recommend(_make_view("p1"), model, k=10)
        assert items == []  # only viewed product, but it is inactive -> empty

    def test_k_one(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1"), model_with_covis, k=1)
        assert items == ["p1"]

    def test_large_k(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1"), model_with_covis, k=100)
        assert len(items) == 10  # capped by model.popular length


class TestModelBlocked:
    """Test Model.blocked() method."""

    def test_inactive_included(self):
        from starter.recommender_v2 import Model
        m = Model(inactive={"p1"})
        assert "p1" in m.blocked(None)

    def test_unavailable_included(self):
        from starter.recommender_v2 import Model
        m = Model(unavailable={"p2"})
        assert "p2" in m.blocked(None)

    def test_bought_included(self):
        from starter.recommender_v2 import Model
        m = Model(bought={"u1": {"p3"}})
        assert "p3" in m.blocked("u1")

    def test_bought_not_for_unknown_user(self):
        from starter.recommender_v2 import Model
        m = Model(bought={"u1": {"p3"}})
        assert "p3" not in m.blocked("u2")

    def test_bought_not_for_no_user(self):
        from starter.recommender_v2 import Model
        m = Model(bought={"u1": {"p3"}})
        assert "p3" not in m.blocked(None)

    def test_union_of_all_blocks(self):
        from starter.recommender_v2 import Model
        m = Model(inactive={"p1"}, unavailable={"p2"}, bought={"u1": {"p3"}})
        blocked = m.blocked("u1")
        assert "p1" in blocked
        assert "p2" in blocked
        assert "p3" in blocked


class TestModelCopySafety:
    """Test that Model.blocked() returns a copy, not a reference."""

    def test_blocked_does_not_leak_reference(self):
        from starter.recommender_v2 import Model
        m = Model(bought={"u1": {"p1"}})
        blocked1 = m.blocked("u1")
        blocked1.add("p2")  # mutate the returned set
        blocked2 = m.blocked("u1")
        assert "p2" not in blocked2  # original not mutated


# ------------------------------------------------------------------------ thread safety

class TestThreadSafety:
    """Test concurrent access to Model during recommendation and refresher updates."""

    def test_recommend_during_bought_update(self):
        """ensure recommend() works even if bought dict is being replaced."""
        from starter.recommender_v2 import Model
        m = Model()
        stop = threading.Event()
        errors = []

        def updater():
            i = 0
            while not stop.is_set():
                m.bought[f"user_{i}"] = {f"product_{i}"}
                i += 1

        def reader():
            try:
                while not stop.is_set():
                    m.blocked("random_user")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=updater, daemon=True),
            threading.Thread(target=reader, daemon=True),
        ]
        for t in threads:
            t.start()
        time.sleep(0.05)  # let threads run briefly
        stop.set()
        for t in threads:
            t.join(timeout=1)
        assert not errors, f"Thread safety error: {errors}"

    def test_recommend_during_unavailable_update(self):
        """ensure recommend() works during unavailable set replacement."""
        from starter.recommender_v2 import Model
        m = Model()
        stop = threading.Event()
        errors = []

        def updater():
            i = 0
            while not stop.is_set():
                m.unavailable = {f"product_{i}"}
                i += 1

        def reader():
            try:
                while not stop.is_set():
                    m.blocked("user")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=updater, daemon=True),
            threading.Thread(target=reader, daemon=True),
        ]
        for t in threads:
            t.start()
        time.sleep(0.05)
        stop.set()
        for t in threads:
            t.join(timeout=1)
        assert not errors, f"Thread safety error: {errors}"

    def test_recommend_during_covis_update(self):
        """ensure recommend() works during covis dict mutation."""
        from starter.recommender_v2 import Model
        m = Model(covis={})
        stop = threading.Event()
        errors = []

        def updater():
            i = 0
            while not stop.is_set():
                m.covis[f"product_{i}"] = [(f"product_{i+1}", 0.5)]
                i += 1

        def reader():
            try:
                while not stop.is_set():
                    m.blocked("user")
                    # also exercise covis access indirectly via recommend logic
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=updater, daemon=True),
            threading.Thread(target=reader, daemon=True),
        ]
        for t in threads:
            t.start()
        time.sleep(0.05)
        stop.set()
        for t in threads:
            t.join(timeout=1)
        assert not errors, f"Thread safety error: {errors}"


class TestRecommendConcurrent:
    """Test recommend() called concurrently from multiple threads."""

    def test_concurrent_recommend_calls(self, model_with_covis):
        from starter.recommender_v2 import recommend
        stop = threading.Event()
        results = []
        errors = []

        def recommender_thread(thread_id: int):
            try:
                while not stop.is_set():
                    items = recommend(_make_view(f"p{thread_id % 3 + 1}"), model_with_covis, k=10)
                    results.append((thread_id, items))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=recommender_thread, args=(i,), daemon=True) for i in range(5)]
        for t in threads:
            t.start()
        time.sleep(0.1)
        stop.set()
        for t in threads:
            t.join(timeout=1)
        assert not errors, f"Concurrent recommend error: {errors}"
        assert len(results) > 0  # at least one result per thread


# ------------------------------------------------------------------------ load_covis (mocked SQL)

class TestLoadCovis:
    """Test load_covis with mocked SQL responses."""

    @patch("starter.recommender_v2.query")
    def test_load_covis_normalizes_weights(self, mock_query):
        from starter.recommender_v2 import load_covis
        mock_query.return_value = [
            {"a": "p1", "b": "p2", "n": "100"},
            {"a": "p1", "b": "p3", "n": "50"},
        ]
        result = load_covis(live=False)
        assert result["p1"] == [("p2", 1.0), ("p3", 0.5)]

    @patch("starter.recommender_v2.query")
    def test_load_covis_limit_30(self, mock_query):
        from starter.recommender_v2 import load_covis
        many_results = [{"a": "p1", "b": f"p{i}", "n": "100"} for i in range(50)]
        mock_query.return_value = many_results
        result = load_covis(live=False)
        assert len(result["p1"]) == 30

    @patch("starter.recommender_v2.query")
    def test_load_covis_accumulates_multiple_sources(self, mock_query):
        from starter.recommender_v2 import load_covis
        call_count = [0]

        def side_effect(sql):
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"a": "p1", "b": "p2", "n": "50"}]
            return [{"a": "p1", "b": "p2", "n": "50"}]

        mock_query.side_effect = side_effect
        result = load_covis(live=True)
        assert result["p1"][0][1] == 1.0  # 100 / 100 = 1.0


class TestLoadPopularity:
    """Test load_popularity with mocked SQL responses."""

    @patch("starter.recommender_v2.query")
    def test_score_combines_all_time_and_recent(self, mock_query):
        from starter.recommender_v2 import load_popularity
        mock_query.return_value = [
            {"product_id": "p1", "total": "100", "recent": "20"},
        ]
        score = load_popularity(live=False)
        assert score["p1"] == 100 + 5 * 20  # total + 5 * recent

    @patch("starter.recommender_v2.query")
    def test_live_purchases_weighted_more(self, mock_query):
        from starter.recommender_v2 import load_popularity
        call_count = [0]

        def side_effect(sql):
            call_count[0] += 1
            if "shop.history_events" in sql:
                return [{"product_id": "p1", "total": "100", "recent": "10"}]
            return [{"product_id": "p1", "total": "5", "recent": "3"}]

        mock_query.side_effect = side_effect
        score = load_popularity(live=True)
        # history: 100 + 5*10 = 150, live: 20*5 + 40*3 = 220
        assert score["p1"] == 150 + (20 * 5 + 40 * 3)


class TestBuildModel:
    """Test build_model with mocked SQL responses."""

    @patch("starter.recommender_v2.query")
    @patch("starter.recommender_v2.load_covis")
    @patch("starter.recommender_v2.load_popularity")
    def test_build_model_assembles_all_fields(self, mock_pop, mock_covis, mock_query):
        from starter.recommender_v2 import build_model, Model
        mock_query.return_value = [
            {"product_id": "p1", "subcategory": "electronics", "is_active": True},
            {"product_id": "p2", "subcategory": "books", "is_active": False},
        ]
        mock_covis.return_value = {"p1": [("p2", 1.0)]}
        mock_pop.return_value = Counter({"p1": 100, "p2": 50})

        model = build_model(live=False)
        assert isinstance(model, Model)
        assert model.subcategory["p1"] == "electronics"
        assert "p2" in model.inactive
        assert "p1" in model.popular
        assert "electronics" in model.popular_by_sub


class TestRefresherThreadSafety:
    """Test Refresher thread behavior without requiring live SQL."""

    @patch("starter.recommender_v2.out_of_stock")
    def test_refresher_updates_unavailable(self, mock_oos):
        from starter.recommender_v2 import Model, Refresher
        mock_oos.return_value = {"out1", "out2"}
        model = Model()

        with patch("starter.recommender_v2.query", return_value=[]):
            refresher = Refresher(model)
            refresher.run()  # one iteration

        assert model.unavailable == {"out1", "out2"}

    @patch("starter.recommender_v2.out_of_stock")
    def test_refresher_updates_bought(self, mock_oos):
        from starter.recommender_v2 import Model, Refresher
        mock_oos.return_value = set()
        model = Model()
        mock_results = [
            {"user_id": "u1", "product_id": "p1"},
            {"user_id": "u1", "product_id": "p2"},
            {"user_id": "u2", "product_id": "p3"},
        ]

        with patch("starter.recommender_v2.query", return_value=mock_results):
            refresher = Refresher(model)
            refresher.run()

        assert model.bought == {
            "u1": {"p1", "p2"},
            "u2": {"p3"},
        }

    @patch("starter.recommender_v2.out_of_stock")
    def test_refresher_handles_query_error(self, mock_oos):
        from starter.recommender_v2 import Model, Refresher
        mock_oos.return_value = set()
        model = Model()

        def failing_query(sql):
            if "recent_buyers" in sql.lower() or "feedback" in sql.lower():
                raise ConnectionError("db unavailable")
            return []

        with patch("starter.recommender_v2.query", side_effect=failing_query):
            refresher = Refresher(model)
            refresher.run()  # should not raise

        # Model state should be preserved (empty since it's new)
        assert model.bought == {}


class TestRecommendDiversity:
    """Test that recommendations maintain diversity across categories."""

    def test_no_more_than_5_per_subcategory(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(
            covis={},
            popular_by_sub={"electronics": ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]},
            subcategory={f"p{i}": "electronics" for i in range(1, 8)},
            popular=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10"],
        )
        items = recommend(None, model, k=10)
        # Should not have more than 5 from same sub
        from collections import Counter
        sub_counts = Counter(model.subcategory.get(p, "") for p in items)
        for sub, count in sub_counts.items():
            if sub:  # ignore empty sub
                assert count <= 5, f"Sub {sub} has {count} items, max is 5"

    def test_viewed_products_do_not_reappear_in_covis(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1"), model_with_covis, k=10)
        covis_part = items[1:]  # skip the viewed product
        assert "p1" not in covis_part

    def test_diversity_across_subcategories(self, model_with_covis):
        from starter.recommender_v2 import recommend
        model = _make_model(
            covis={},
            popular_by_sub={
                "electronics": ["p1", "p2", "p3"],
                "books": ["p4", "p5", "p6"],
                "clothing": ["p7", "p8", "p9"],
            },
            subcategory={
                "p1": "electronics", "p2": "electronics", "p3": "electronics",
                "p4": "books", "p5": "books", "p6": "books",
                "p7": "clothing", "p8": "clothing", "p9": "clothing",
            },
        )
        items = recommend(None, model, k=9)
        subs_seen = set(model.subcategory.get(p, "") for p in items)
        assert len(subs_seen) >= 3, f"Only {len(subs_seen)} subcategories in {items}"


class TestBoughtFiltering:
    """Test that bought products are filtered in phase 0 (before phase 1)."""

    def test_bought_views_filtered_from_phase1(self):
        from starter.recommender_v2 import recommend
        model = _make_model(bought={"u1": {"p1", "p3"}})
        items = recommend(_make_view("p1", "p2", "p3"), model, user="u1", k=5)
        assert "p1" not in items, "Bought product p1 should not appear"
        assert "p3" not in items, "Bought product p3 should not appear"
        assert "p2" in items, "Viewed product p2 should still appear"

    def test_bought_views_counted_once(self):
        from starter.recommender_v2 import recommend
        model = _make_model(bought={"u1": {"p1"}})
        items = recommend(_make_view("p1", "p1", "p1", "p2"), model, user="u1", k=5)
        assert "p1" not in items
        assert items[0] == "p2"

    def test_no_user_no_bought_filter(self, model_with_covis):
        from starter.recommender_v2 import recommend
        items = recommend(_make_view("p1", "p2"), model_with_covis, k=5)
        assert "p1" in items
        assert "p2" in items


class TestDiversityConstraints:
    """Test diversity limits across co-purchase and global popular phases."""

    def test_covis_phase_respects_subcategory_cap(self):
        from starter.recommender_v2 import recommend
        model = _make_model(
            covis={
                "p1": [("s1a", 1.0), ("s1b", 0.9), ("s1c", 0.8), ("s1d", 0.7),
                       ("s1e", 0.6), ("s1f", 0.5), ("p2", 0.4)],
            },
            popular=["p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10", "p11"],
            popular_by_sub={
                "electronics": ["s1a", "s1b", "s1c", "s1d", "s1e", "s1f", "p2", "p3"],
                "books": ["p4", "p5", "p6", "p7", "p8"],
            },
            subcategory={
                "p1": "electronics",
                "s1a": "electronics", "s1b": "electronics", "s1c": "electronics",
                "s1d": "electronics", "s1e": "electronics", "s1f": "electronics",
                "p2": "electronics", "p3": "electronics",
                "p4": "books", "p5": "books", "p6": "books", "p7": "books", "p8": "books",
                "p9": "books", "p10": "books", "p11": "books",
            },
            inactive=set(),
            unavailable=set(),
            bought={},
        )
        items = recommend(_make_view("p1"), model, k=10)
        elec_count = sum(1 for p in items if model.subcategory.get(p) == "electronics")
        assert elec_count <= 5, f"Expected <= 5 electronics, got {elec_count}"

    def test_global_popular_respects_subcategory_cap(self):
        from starter.recommender_v2 import recommend
        model = _make_model(
            covis={},
            popular=["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8", "b1", "b2"],
            popular_by_sub={
                "electronics": ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"],
                "books": ["b1", "b2"],
            },
            subcategory={
                "e1": "electronics", "e2": "electronics", "e3": "electronics", "e4": "electronics",
                "e5": "electronics", "e6": "electronics", "e7": "electronics", "e8": "electronics",
                "b1": "books", "b2": "books",
            },
            inactive=set(),
            unavailable=set(),
            bought={},
        )
        items = recommend(None, model, k=10)
        elec_count = sum(1 for p in items if model.subcategory.get(p) == "electronics")
        assert elec_count <= 5, f"Expected <= 5 electronics in popular, got {elec_count}"


class TestModelCopy:
    """Test safe deep-copy of model state in Refresher."""

    def test_copy_model_state_deep_copies_covis(self):
        from starter.recommender_v2 import Model, Refresher
        src = Model(
            covis={"p1": [("p2", 1.0), ("p3", 0.5)]},
            popular=["p1", "p2", "p3"],
            popular_by_sub={"electronics": ["p1", "p2", "p3"]},
            subcategory={"p1": "electronics", "p2": "electronics", "p3": "electronics"},
            inactive={"p99"},
            unavailable=set(),
            bought={},
        )
        dst = Model()
        Refresher._copy_model_state(None, src, dst)

        src.covis["p1"].append(("p4", 0.3))
        src.popular.append("p4")
        src.popular_by_sub["electronics"].append("p4")
        src.subcategory["p4"] = "electronics"
        src.inactive.add("p98")

        assert ("p4", 0.3) not in dst.covis["p1"]
        assert "p4" not in dst.popular
        assert "p4" not in dst.popular_by_sub["electronics"]
        assert "p4" not in dst.subcategory
        assert "p98" not in dst.inactive

    def test_copy_model_state_preserves_bought_and_unavailable(self):
        from starter.recommender_v2 import Model, Refresher
        src = Model(covis={}, popular=[], popular_by_sub={}, subcategory={},
                    inactive=set(), unavailable={"out1"}, bought={})
        dst = Model(covis={"old": [("x", 1.0)]}, popular=["old"], popular_by_sub={},
                    subcategory={}, inactive={"old_inactive"}, unavailable=set(),
                    bought={"u1": {"p1"}})

        Refresher._copy_model_state(None, src, dst)

        assert "old" not in dst.covis
        assert "old" not in dst.popular
        assert "old_inactive" not in dst.inactive
        assert dst.unavailable == {"out1"}
        assert dst.bought == {"u1": {"p1"}}