from fastapi import APIRouter, Request, Query

from catalog.search import search_tables, get_table_detail
from catalog.lineage import get_lineage

router = APIRouter()


@router.get("/search")
async def catalog_search(request: Request, q: str = Query(..., min_length=1)):
    kb = request.app.state.kb
    results = search_tables(kb, q)
    return results


@router.get("/table/{name}")
async def table_detail(name: str, request: Request):
    kb = request.app.state.kb
    return get_table_detail(kb, name)


@router.get("/lineage")
async def full_lineage(request: Request):
    """Return the full lineage graph for visualization."""
    kb = request.app.state.kb
    return kb.lineage


@router.get("/lineage/{table}")
async def table_lineage(
    table: str,
    request: Request,
    direction: str = Query("both", regex="^(upstream|downstream|both)$"),
):
    kb = request.app.state.kb
    return get_lineage(kb, table, direction)
