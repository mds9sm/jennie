"""
Layer 6: DOMO REST Client Tests

Tests the DOMO client module with all HTTP calls mocked.
Verifies response shapes, error handling, and auth behavior.
"""

import pytest
from unittest.mock import patch, MagicMock


# =============================================================================
# Helpers
# =============================================================================

def _make_mock_response(status_code: int, json_data=None, text: str = ""):
    """Create a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _fresh_client():
    """Import and reset the domo_client module state."""
    import connectors.domo_client as dc
    dc._configured = False
    dc._access_token = ""
    dc._client_id = ""
    dc._client_secret = ""
    return dc


# =============================================================================
# Configuration
# =============================================================================

def test_not_configured_returns_error():
    dc = _fresh_client()
    result = dc.search_datasets("test")
    assert "error" in result
    assert "not configured" in result["error"].lower()


def test_configure_sets_state():
    dc = _fresh_client()
    with patch("connectors.domo_client.requests.get") as mock_get:
        mock_get.return_value = _make_mock_response(200, {"access_token": "tok123"})
        dc.configure("my_client_id", "my_secret")
    assert dc.is_configured()
    assert dc._access_token == "tok123"


# =============================================================================
# _api adds auth header
# =============================================================================

def test_api_adds_auth_header():
    dc = _fresh_client()
    dc._configured = True
    dc._access_token = "test_token"

    with patch("connectors.domo_client.requests.request") as mock_req:
        mock_req.return_value = _make_mock_response(200, {"data": "ok"})
        result = dc._api("GET", "/v1/test")

    mock_req.assert_called_once()
    call_kwargs = mock_req.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
    assert "bearer test_token" in headers.get("Authorization", "")


# =============================================================================
# search_datasets
# =============================================================================

def test_search_datasets_returns_correct_shape():
    dc = _fresh_client()
    dc._configured = True
    dc._access_token = "tok"

    mock_data = [
        {"id": "ds1", "name": "User Events Daily", "owner": {"name": "Data Team"}, "rows": 5000, "updatedAt": "2024-01-01"},
        {"id": "ds2", "name": "Cut Sessions", "owner": {"name": "Data Team"}, "rows": 3000, "updatedAt": "2024-01-02"},
    ]

    with patch("connectors.domo_client.requests.request") as mock_req:
        mock_req.return_value = _make_mock_response(200, mock_data)
        result = dc.search_datasets("user")

    assert "query" in result
    assert "count" in result
    assert "datasets" in result
    assert result["count"] == 1  # only "User Events Daily" matches "user"
    assert result["datasets"][0]["name"] == "User Events Daily"


# =============================================================================
# get_dataset_metadata
# =============================================================================

def test_get_dataset_metadata_returns_correct_shape():
    dc = _fresh_client()
    dc._configured = True
    dc._access_token = "tok"

    mock_data = {
        "name": "User Events",
        "description": "All user events",
        "owner": {"name": "Data Team"},
        "createdAt": "2024-01-01",
        "updatedAt": "2024-06-01",
        "rows": 10000,
        "columns": 25,
        "dataProviderType": "api",
    }

    with patch("connectors.domo_client.requests.request") as mock_req:
        mock_req.return_value = _make_mock_response(200, mock_data)
        result = dc.get_dataset_metadata("ds123")

    assert result["dataset_id"] == "ds123"
    assert result["name"] == "User Events"
    assert result["rows"] == 10000
    assert result["columns"] == 25
    assert "owner" in result


# =============================================================================
# get_dataset_schema
# =============================================================================

def test_get_dataset_schema_returns_correct_shape():
    dc = _fresh_client()
    dc._configured = True
    dc._access_token = "tok"

    mock_data = {
        "name": "User Events",
        "schema": {
            "columns": [
                {"name": "user_id", "type": "LONG"},
                {"name": "event_date", "type": "DATE"},
            ]
        },
    }

    with patch("connectors.domo_client.requests.request") as mock_req:
        mock_req.return_value = _make_mock_response(200, mock_data)
        result = dc.get_dataset_schema("ds123")

    assert result["dataset_id"] == "ds123"
    assert result["column_count"] == 2
    assert result["columns"][0]["name"] == "user_id"
    assert result["columns"][1]["type"] == "DATE"


# =============================================================================
# list_dashboards
# =============================================================================

def test_list_dashboards_returns_correct_shape():
    dc = _fresh_client()
    dc._configured = True
    dc._access_token = "tok"

    pages_data = [
        {"id": 1, "name": "Executive Dashboard"},
        {"id": 2, "name": "Ops Dashboard"},
    ]
    detail_data = {"cardIds": [101, 102, 103], "children": []}

    call_count = 0

    def mock_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "/v1/pages?" in url:
            return _make_mock_response(200, pages_data)
        return _make_mock_response(200, detail_data)

    with patch("connectors.domo_client.requests.request", side_effect=mock_request):
        result = dc.list_dashboards()

    assert "dashboards" in result
    assert "count" in result
    assert result["count"] == 2
    assert result["dashboards"][0]["name"] == "Executive Dashboard"
    assert result["dashboards"][0]["card_count"] == 3


# =============================================================================
# get_dashboard_detail
# =============================================================================

def test_get_dashboard_detail_returns_correct_shape():
    dc = _fresh_client()
    dc._configured = True
    dc._access_token = "tok"

    page_data = {
        "name": "Executive Dashboard",
        "cardIds": [101],
        "children": [{"id": 10, "name": "Sub Page"}],
    }
    card_data = {
        "cardTitle": "Daily Revenue",
        "type": "chart",
        "dataSourceId": "ds-rev",
    }

    def mock_request(method, url, **kwargs):
        if "/v1/cards/" in url:
            return _make_mock_response(200, card_data)
        return _make_mock_response(200, page_data)

    with patch("connectors.domo_client.requests.request", side_effect=mock_request):
        result = dc.get_dashboard_detail("page1")

    assert result["page_id"] == "page1"
    assert result["name"] == "Executive Dashboard"
    assert result["card_count"] == 1
    assert result["cards"][0]["title"] == "Daily Revenue"
    assert len(result["children"]) == 1
