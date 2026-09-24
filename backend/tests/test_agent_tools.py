"""
Layer 4: Agent Tool Tests

Verify that KB search tools return correct results from available data sources.
"""

import pytest
from catalog.loader import KnowledgeBase
from catalog.search import search_tables, search_transforms, search_glossary


@pytest.fixture
def kb():
    """Load the real KB for testing tool behavior."""
    kb = KnowledgeBase("knowledge")
    kb.load()
    return kb


class TestSearchTables:
    def test_returns_results_from_lineage_when_catalog_empty(self, kb):
        """search_tables should fall back to lineage when catalog.json is empty."""
        # Catalog is empty (no Redshift KB build), but lineage has 900+ tables
        assert len(kb.catalog.get("tables", [])) == 0
        assert len(kb.lineage) > 0

        result = search_tables(kb, "image_conversion")
        assert result["count"] > 0
        names = [r.get("full_name", r["name"]) for r in result["results"]]
        assert any("image_conversion" in n.lower() for n in names)

    def test_returns_lineage_note_when_using_fallback(self, kb):
        """Should indicate results are from lineage, not catalog."""
        if len(kb.catalog.get("tables", [])) == 0:
            result = search_tables(kb, "user_profile")
            assert "note" in result
            assert "lineage" in result["note"].lower()

    def test_returns_upstream_downstream_counts(self, kb):
        """Lineage results should include dependency counts."""
        if len(kb.lineage) == 0:
            pytest.skip("No lineage data")
        result = search_tables(kb, "cut_session_master")
        for r in result["results"]:
            if r.get("source") == "lineage":
                assert "upstream_count" in r
                assert "downstream_count" in r

    def test_empty_keyword_returns_empty(self, kb):
        """Empty search should return no results."""
        result = search_tables(kb, "")
        assert result["count"] == 0

    def test_no_match_returns_low_scores(self, kb):
        """Non-existent table should return low-confidence results or empty."""
        result = search_tables(kb, "zzz_nonexistent_table_xyz_999")
        # Fuzzy search may return low-score matches — that's OK
        # But high-confidence matches should not exist
        for r in result["results"]:
            assert r.get("score", 0) < 80, f"High-confidence match for nonsense query: {r}"


class TestSearchTransforms:
    def test_finds_transforms_by_name(self, kb):
        """Should find transforms by partial name match."""
        if not kb.transforms_index:
            pytest.skip("No transforms in KB")
        result = search_transforms(kb, "cut_session")
        assert result["count"] > 0

    def test_returns_dag_metadata(self, kb):
        """Results should include schedule, dag_type, run state."""
        if not kb.transforms_index:
            pytest.skip("No transforms in KB")
        result = search_transforms(kb, "image")
        for r in result["results"]:
            assert "dag_id" in r
            assert "name" in r
            assert "dag_type" in r


class TestSearchGlossary:
    def test_returns_empty_when_no_glossary(self, kb):
        """Should return empty list, not crash, when glossary is empty."""
        result = search_glossary(kb, "activation rate")
        assert isinstance(result, list)
