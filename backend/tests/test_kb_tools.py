"""
Layer 5: Knowledge Base Tool Tests

Tests for KB build components:
- DOMO parser (parse configs, views, downstream_dags)
- DOMO S3 enricher (parse S3 paths, infer pillar, infer metric type)
- Catalog search (fuzzy search, lineage fallback, profile fallback)
- KB loader (load, get_view_detail, get_transform_detail)
"""

import json
import os
import tempfile
import pytest
from pathlib import Path


# =============================================================================
# DOMO Parser: parse_domo_refresh_configs
# =============================================================================

def test_parse_domo_refresh_configs_empty_dir():
    """Returns empty list when directory doesn't exist."""
    from catalog_engine.domo_parser import parse_domo_refresh_configs
    result = parse_domo_refresh_configs("/nonexistent/path")
    assert result == []


def test_parse_domo_refresh_configs_valid_yaml():
    """Parses a valid DOMO refresh config."""
    from catalog_engine.domo_parser import parse_domo_refresh_configs

    with tempfile.TemporaryDirectory() as tmpdir:
        conf_dir = Path(tmpdir) / "dags" / "domo_refresh" / "conf"
        conf_dir.mkdir(parents=True)

        config = {
            "DOMO__test_refresh": {
                "email_id": ["data@example.com"],
                "tags": ["pillar_5"],
                "environment": {
                    "prd": {"s3_unload_url": "s3://prod-bi-export/prd_dw/analytics/"}
                },
                "objects": {
                    "engagement_depth_view": {
                        "schema": "analytics",
                        "domo_dataset_id": "abc-123",
                        "s3_unload_path": "engagement_depth/",
                        "columns": "*",
                    }
                },
            }
        }

        with open(conf_dir / "test.yaml", "w") as f:
            import yaml
            yaml.dump(config, f)

        result = parse_domo_refresh_configs(tmpdir)
        assert len(result) == 1
        assert result[0]["dag_name"] == "DOMO__test_refresh"
        assert result[0]["view_name"] == "engagement_depth_view"
        assert result[0]["domo_dataset_id"] == "abc-123"
        assert result[0]["schema"] == "analytics"


# =============================================================================
# DOMO Parser: parse_transform_views
# =============================================================================

def test_parse_transform_views_empty_dir():
    from catalog_engine.domo_parser import parse_transform_views
    result = parse_transform_views("/nonexistent/path")
    assert result == []


def test_parse_transform_views_with_view_config():
    from catalog_engine.domo_parser import parse_transform_views

    with tempfile.TemporaryDirectory() as tmpdir:
        conf_dir = Path(tmpdir) / "dags" / "transform" / "conf"
        conf_dir.mkdir(parents=True)
        sql_dir = Path(tmpdir) / "dags" / "transform" / "sql"
        sql_dir.mkdir(parents=True)

        # Write SQL file
        (sql_dir / "engagement_view.sql").write_text(
            "CREATE OR REPLACE VIEW analytics.engagement_depth_view AS\n"
            "SELECT * FROM prd_dw.analytics.user_events\n"
            "JOIN prd_dw.analytics.users ON user_events.user_id = users.id"
        )

        config = {
            "TRANSFORM_DAG__engagement": {
                "views": {
                    "REFRESH_ENGAGEMENT_VIEW": {
                        "sql": "sql/engagement_view.sql",
                        "params": {"view_schema": "analytics", "view_name": "engagement_depth_view"},
                        "conn_id": "redshift_prd",
                    }
                }
            }
        }

        with open(conf_dir / "engagement.yaml", "w") as f:
            import yaml
            yaml.dump(config, f)

        result = parse_transform_views(tmpdir)
        assert len(result) == 1
        assert result[0]["dag_name"] == "TRANSFORM_DAG__engagement"
        assert result[0]["view_task_name"] == "REFRESH_ENGAGEMENT_VIEW"
        assert len(result[0]["source_tables"]) > 0


# =============================================================================
# DOMO Parser: parse_downstream_dags
# =============================================================================

def test_parse_downstream_dags_extracts_links():
    from catalog_engine.domo_parser import parse_downstream_dags

    with tempfile.TemporaryDirectory() as tmpdir:
        conf_dir = Path(tmpdir) / "dags" / "transform" / "conf"
        conf_dir.mkdir(parents=True)

        config = {
            "TRANSFORM_DAG__upstream": {
                "downstream_dags": ["TRANSFORM_DAG__downstream_1", "DOMO__refresh_1"],
            },
            "TRANSFORM_DAG__no_downstream": {
                "schedule": "@daily",
            },
        }

        with open(conf_dir / "test.yaml", "w") as f:
            import yaml
            yaml.dump(config, f)

        result = parse_downstream_dags(tmpdir)
        assert "TRANSFORM_DAG__upstream" in result
        assert len(result["TRANSFORM_DAG__upstream"]) == 2
        assert "TRANSFORM_DAG__no_downstream" not in result


# =============================================================================
# DOMO S3 Enricher: _parse_s3_path
# =============================================================================

def test_parse_s3_path_valid():
    from catalog_engine.domo_s3_enricher import _parse_s3_path
    bucket, prefix = _parse_s3_path("s3://prod-bi-export/prd_dw/analytics/engagement/")
    assert bucket == "prod-bi-export"
    assert prefix == "prd_dw/analytics/engagement/"


def test_parse_s3_path_no_prefix():
    from catalog_engine.domo_s3_enricher import _parse_s3_path
    bucket, prefix = _parse_s3_path("s3://mybucket")
    assert bucket == "mybucket"
    assert prefix == ""


def test_parse_s3_path_empty():
    from catalog_engine.domo_s3_enricher import _parse_s3_path
    bucket, prefix = _parse_s3_path("")
    assert bucket == ""
    assert prefix == ""


def test_parse_s3_path_not_s3():
    from catalog_engine.domo_s3_enricher import _parse_s3_path
    bucket, prefix = _parse_s3_path("https://example.com/path")
    assert bucket == ""
    assert prefix == ""


# =============================================================================
# DOMO S3 Enricher: _infer_pillar
# =============================================================================

def test_infer_pillar_onboard():
    from catalog_engine.domo_s3_enricher import _infer_pillar
    assert _infer_pillar({"name": "onboard_activation_funnel", "dag_name": "DAG__onboard"}) == "Onboard"


def test_infer_pillar_trigger_return():
    from catalog_engine.domo_s3_enricher import _infer_pillar
    assert _infer_pillar({"name": "dau_weekly", "dag_name": "DAG__retention"}) == "Trigger Return"


def test_infer_pillar_marketing():
    from catalog_engine.domo_s3_enricher import _infer_pillar
    assert _infer_pillar({"name": "churn_analysis", "dag_name": "", "domo_tags": ["braze"]}) == "Marketing"


def test_infer_pillar_unknown():
    from catalog_engine.domo_s3_enricher import _infer_pillar
    assert _infer_pillar({"name": "misc_report", "dag_name": ""}) == ""


# =============================================================================
# DOMO S3 Enricher: _infer_metric_type
# =============================================================================

def test_infer_metric_type_north_star():
    from catalog_engine.domo_s3_enricher import _infer_metric_type
    assert _infer_metric_type({"name": "north_star_kpi"}) == "north_star"


def test_infer_metric_type_time_series():
    from catalog_engine.domo_s3_enricher import _infer_metric_type
    assert _infer_metric_type({"name": "daily_active_users"}) == "time_series"


def test_infer_metric_type_direct_unload():
    from catalog_engine.domo_s3_enricher import _infer_metric_type
    assert _infer_metric_type({"name": "something", "type": "direct_unload"}) == "direct_unload"


def test_infer_metric_type_default():
    from catalog_engine.domo_s3_enricher import _infer_metric_type
    assert _infer_metric_type({"name": "something_general"}) == "metric"


# =============================================================================
# Catalog Search: search_tables
# =============================================================================

def test_search_tables_with_catalog_data():
    from catalog.search import search_tables
    from catalog.loader import KnowledgeBase

    kb = KnowledgeBase("knowledge")
    kb.catalog = {
        "tables": [
            {"name": "user_events", "schema": "analytics", "description": "All user events", "columns": [{"name": "user_id"}]},
            {"name": "cut_sessions", "schema": "analytics", "description": "Cutting sessions", "columns": [{"name": "session_id"}]},
        ]
    }
    kb.lineage = {}
    kb.table_profiles = {}

    result = search_tables(kb, "user events")
    assert result["count"] > 0
    assert result["results"][0]["name"] == "user_events"


def test_search_tables_lineage_fallback():
    from catalog.search import search_tables
    from catalog.loader import KnowledgeBase

    kb = KnowledgeBase("knowledge")
    kb.catalog = {"tables": []}
    kb.lineage = {
        "analytics.user_events": {"upstream": ["raw.events"], "downstream": ["analytics.dau"]},
    }
    kb.table_profiles = {}

    result = search_tables(kb, "user_events")
    assert result["count"] > 0
    assert "lineage" in result["results"][0].get("source", "")


def test_search_tables_profile_fallback():
    from catalog.search import search_tables
    from catalog.loader import KnowledgeBase

    kb = KnowledgeBase("knowledge")
    kb.catalog = {"tables": []}
    kb.lineage = {}
    kb.table_profiles = {
        "analytics.user_events": {"schema": "analytics", "table": "user_events", "row_count": 1000, "type": "fact"},
    }

    result = search_tables(kb, "user_events")
    assert result["count"] > 0
    assert result["results"][0].get("source") == "table_ops_profile"


def test_search_tables_empty_kb():
    from catalog.search import search_tables
    from catalog.loader import KnowledgeBase

    kb = KnowledgeBase("knowledge")
    kb.catalog = {"tables": []}
    kb.lineage = {}
    kb.table_profiles = {}

    result = search_tables(kb, "anything")
    assert result["count"] == 0


# =============================================================================
# KB Loader
# =============================================================================

def test_kb_load_from_knowledge_dir():
    """KnowledgeBase.load() works with the real knowledge directory."""
    from catalog.loader import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    kb.load()
    # Should load without error; check the claude_md is populated
    assert len(kb.claude_md) > 0


def test_kb_get_view_detail_nonexistent():
    from catalog.loader import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    result = kb.get_view_detail("nonexistent_view_xyz")
    assert result is None


def test_kb_get_transform_detail_nonexistent():
    from catalog.loader import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    result = kb.get_transform_detail("nonexistent_dag_xyz")
    assert result is None


def test_kb_load_with_temp_dir():
    """KnowledgeBase.load() with missing files produces sensible defaults."""
    from catalog.loader import KnowledgeBase
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        kb.load()
        assert kb.catalog == {"tables": []}
        assert kb.transforms_index == []
        assert kb.lineage == {}
        assert kb.glossary == {}
