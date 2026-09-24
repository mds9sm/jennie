"""Documentation API — serves product docs as structured content."""
import logging
from pathlib import Path
from fastapi import APIRouter

logger = logging.getLogger("genie.docs")
router = APIRouter()

# Docker-compose mounts ./docs:/app/docs. In K8s, docs are baked into backend/docs/.
_DOCS_MOUNT = Path("/app/docs")
_DOCS_BUNDLED = Path(__file__).resolve().parent.parent / "docs"
DOCS_DIR = _DOCS_MOUNT if _DOCS_MOUNT.is_dir() and any(_DOCS_MOUNT.glob("*.md")) else _DOCS_BUNDLED


@router.get("/pages")
async def list_pages():
    """List all available doc pages."""
    pages = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        # Read first line as title
        title = f.stem.replace("_", " ").title()
        try:
            first_line = f.read_text().split("\n")[0].strip("# ").strip()
            if first_line:
                title = first_line
        except Exception:
            pass
        pages.append({"slug": f.stem, "title": title, "filename": f.name})
    return pages


@router.get("/pages/{slug}")
async def get_page(slug: str):
    """Get a doc page content as markdown."""
    path = DOCS_DIR / f"{slug}.md"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"Doc page '{slug}' not found")
    content = path.read_text()
    # Extract title from first # heading
    title = slug.replace("_", " ").title()
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line.strip("# ").strip()
            break
    return {"slug": slug, "title": title, "content": content}
