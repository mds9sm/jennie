"""
Layer 7: Query Safety Tests

validate_query_safety() must block all non-read operations.
Only SELECT, EXPLAIN, ANALYZE, SET, SHOW, and WITH are allowed.
"""

import pytest
from connectors.redshift import validate_query_safety


# =============================================================================
# Allowed statements
# =============================================================================

def test_select_allowed():
    validate_query_safety("SELECT * FROM analytics.user_events WHERE date > '2024-01-01'")


def test_select_with_cte_allowed():
    validate_query_safety("WITH cte AS (SELECT 1) SELECT * FROM cte")


def test_explain_allowed():
    validate_query_safety("EXPLAIN SELECT * FROM analytics.user_events")


def test_analyze_allowed():
    validate_query_safety("ANALYZE analytics.user_events")


def test_set_allowed():
    validate_query_safety("SET search_path TO analytics")


def test_show_allowed():
    validate_query_safety("SHOW search_path")


def test_select_case_insensitive():
    validate_query_safety("select count(*) from analytics.dau")


def test_select_with_leading_whitespace():
    validate_query_safety("   SELECT 1")


# =============================================================================
# Blocked statements
# =============================================================================

def test_insert_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("INSERT INTO users VALUES (1, 'hacker')")


def test_update_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("UPDATE users SET role = 'admin' WHERE id = 1")


def test_delete_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("DELETE FROM users WHERE id = 1")


def test_drop_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("DROP TABLE users")


def test_truncate_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("TRUNCATE TABLE analytics.user_events")


def test_create_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("CREATE TABLE hacked (id int)")


def test_alter_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("ALTER TABLE users ADD COLUMN hacked boolean")


def test_grant_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("GRANT ALL ON users TO public")


def test_copy_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("COPY users FROM 's3://bucket/data'")


# =============================================================================
# Multi-statement attacks
# =============================================================================

def test_multi_statement_select_then_drop():
    """SELECT followed by DROP must be blocked."""
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("SELECT 1; DROP TABLE users")


def test_multi_statement_select_then_delete():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("SELECT 1; DELETE FROM users")


# =============================================================================
# Comment injection
# =============================================================================

def test_comment_injection_single_line():
    """SQL comment should be stripped, revealing the hidden DROP."""
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("SELECT 1; -- safe\nDROP TABLE users")


def test_comment_injection_block_comment():
    """Block comments should be stripped."""
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_query_safety("SELECT 1; /* harmless */ DROP TABLE users")


def test_safe_select_with_comment():
    """A safe SELECT with a comment should still pass."""
    validate_query_safety("SELECT 1 -- just a number")


def test_safe_select_with_block_comment():
    validate_query_safety("SELECT /* count */ 1 FROM analytics.dau")
