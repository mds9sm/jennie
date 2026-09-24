"""
Repo Parser — secondary knowledge source.

Extracts git metadata from your data platform repo:
- Who last changed each DAG config (git blame)
- When it was last updated
- Recent commit history per file
- YAML config metadata (schedule, tags, params, owners)

The primary knowledge (SQL, table names, lineage) comes from MWAA.
This module provides the "who/when/why" context around changes.
"""

import ast
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("genie.catalog_engine.repo_parser")

# Known DAG directory types
DAG_TYPES = {
    "transform": "transform",
    "dq_sync": "dq_validation",
    "events_v3": "events",
    "ingest_s3": "ingestion",
    "ingest_sqs": "ingestion",
    "personalization": "personalization",
    "statsig": "statsig",
    "extract": "extract",
    "ingestion_pipelines": "ingestion",
    "braze": "braze",
}


def _git_blame_summary(repo_path: str, filepath: str) -> dict:
    """Get last author and date from git blame for a file."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an|%ae|%aI|%s", "--", filepath],
            cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|", 3)
            if len(parts) == 4:
                return {
                    "last_author": parts[0],
                    "last_author_email": parts[1],
                    "last_modified": parts[2],
                    "last_commit_message": parts[3],
                }
    except Exception:
        pass
    return {}


def _git_file_history(repo_path: str, filepath: str, limit: int = 5) -> list[dict]:
    """Get recent commit history for a file."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--format=%H|%an|%aI|%s", "--", filepath],
            cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []

        history = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                history.append({
                    "sha": parts[0][:8],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })
        return history
    except Exception:
        return []


def _extract_dag_config(filepath: Path, content: dict, dag_type: str) -> list[dict]:
    """
    Extract DAG metadata from a YAML config file.
    Focuses on config/ownership metadata — not SQL lineage (that's MWAA's job).
    """
    results: list[dict] = []

    for dag_name, dag_cfg in content.items():
        if not isinstance(dag_cfg, dict):
            continue

        schedule = (
            dag_cfg.get("schedule_interval")
            or dag_cfg.get("schedule")
            or ""
        )

        # Extract target table from default_params
        target_table = ""
        target_db = ""
        params = dag_cfg.get("default_params", {})
        for env_key in ("prd", "prod", "nonprod"):
            env_params = params.get(env_key, {})
            if isinstance(env_params, dict):
                t_table = (
                    env_params.get("target_table")
                    or env_params.get("table_name")
                    or env_params.get("destination_table", "")
                )
                t_schema = env_params.get("target_schema", "")
                t_db = env_params.get("database", "")
                if t_table and (env_key in ("prd", "prod") or not target_table):
                    target_table = f"{t_schema}.{t_table}" if t_schema else t_table
                    target_db = t_db

        tags = dag_cfg.get("tags", [])
        notify = dag_cfg.get("notify_email", [])

        # Count SQL steps
        steps = dag_cfg.get("steps", {})
        sql_step_count = 0
        sql_files: list[str] = []
        if isinstance(steps, dict):
            for step_cfg in steps.values():
                if isinstance(step_cfg, dict) and step_cfg.get("sql"):
                    sql_step_count += 1
                    sql_val = step_cfg["sql"]
                    if isinstance(sql_val, str):
                        sql_files.append(sql_val)
                    elif isinstance(sql_val, list):
                        sql_files.extend(s for s in sql_val if isinstance(s, str))

        entry: dict[str, Any] = {
            "name": dag_name,
            "dag_id": dag_name,
            "dag_type": dag_type,
            "target_table": target_table,
            "schedule": str(schedule) if schedule else "",
            "tags": tags if isinstance(tags, list) else [],
            "notify_email": notify if isinstance(notify, list) else [],
            "sql_step_count": sql_step_count,
            "sql_files": sql_files,
            "yaml_file": str(filepath),
        }

        if dag_cfg.get("delta_load") is not None:
            entry["delta_load"] = dag_cfg["delta_load"]
        if dag_cfg.get("refill_days") is not None:
            entry["refill_days"] = dag_cfg["refill_days"]
        if dag_cfg.get("days_per_batch") is not None:
            entry["days_per_batch"] = dag_cfg["days_per_batch"]
        if dag_cfg.get("max_active_runs") is not None:
            entry["max_active_runs"] = dag_cfg["max_active_runs"]
        if target_db:
            entry["database"] = target_db

        results.append(entry)

    return results


def parse_repo(repo_path: str) -> dict:
    """
    Parse your data platform repo for DAG configs + git metadata.

    Returns:
        {
            "transforms": [...],   # DAG configs with git metadata
            "lineage": {},         # empty — lineage comes from MWAA
            "stats": {...},
        }
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        logger.warning("Repo path does not exist: %s", repo_path)
        return {"transforms": [], "lineage": {}, "stats": {}}

    dags_dir = repo / "dags"
    if not dags_dir.is_dir():
        logger.warning("No dags/ directory in %s", repo_path)
        return {"transforms": [], "lineage": {}, "stats": {}}

    transforms: list[dict] = []
    yaml_count = 0
    type_counts: dict[str, int] = {}

    for dag_dir_name, dag_type in DAG_TYPES.items():
        conf_dir = dags_dir / dag_dir_name / "conf"
        if not conf_dir.is_dir():
            continue

        yaml_files = list(conf_dir.glob("*.yaml")) + list(conf_dir.glob("*.yml"))
        logger.info("Scanning %s/conf/: %d YAML files", dag_dir_name, len(yaml_files))

        for yaml_path in yaml_files:
            if "_deprecated" in yaml_path.name:
                continue

            try:
                with open(yaml_path) as f:
                    content = yaml.safe_load(f)
            except Exception as e:
                logger.debug("Skipping %s: %s", yaml_path, e)
                continue

            if not content or not isinstance(content, dict):
                continue

            yaml_count += 1
            dag_configs = _extract_dag_config(yaml_path, content, dag_type)

            for cfg in dag_configs:
                # Add git metadata
                rel_path = str(yaml_path.relative_to(repo))
                blame = _git_blame_summary(repo_path, rel_path)
                cfg.update(blame)
                cfg["recent_history"] = _git_file_history(repo_path, rel_path, limit=5)

                transforms.append(cfg)
                type_counts[dag_type] = type_counts.get(dag_type, 0) + 1

    logger.info(
        "Parsed repo: %d DAG configs from %d YAML files",
        len(transforms), yaml_count,
    )
    logger.info("By type: %s", type_counts)

    return {
        "transforms": transforms,
        "lineage": {},  # lineage comes from MWAA, not repo
        "stats": {
            "yaml_parsed": yaml_count,
            "by_type": type_counts,
        },
    }


# ---------------------------------------------------------------------------
# Extended parser: reads ALL file types in a repo (not just DAG YAML/SQL)
# ---------------------------------------------------------------------------

# Directories to always skip
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".tox", ".mypy_cache", ".pytest_cache", "venv", ".venv", "env"}

# Binary extensions to skip
_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".tiff",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".whl", ".egg", ".class", ".jar",
    ".parquet", ".avro", ".orc", ".feather",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".sqlite", ".db",
}

# Max file size to read (10 KB)
_MAX_READ_BYTES = 10 * 1024

# Max total files to process
_MAX_FILES = 500


def _is_dag_yaml(filepath: Path, repo_root: Path) -> bool:
    """Return True if this file is already handled by the standard parse_repo (DAG YAML configs)."""
    try:
        rel = filepath.relative_to(repo_root / "dags")
    except ValueError:
        return False
    parts = rel.parts
    # Pattern: dags/<dag_type>/conf/*.yaml
    if len(parts) >= 3 and parts[1] == "conf" and parts[0] in DAG_TYPES:
        return True
    return False


def _extract_python_summary(content: str) -> dict:
    """Extract docstrings, class names, and function names from a Python file (first 50 lines)."""
    lines = content.split("\n")[:50]
    snippet = "\n".join(lines)
    result: dict[str, Any] = {"classes": [], "functions": [], "docstring": None}

    try:
        tree = ast.parse(snippet)
    except SyntaxError:
        # If first 50 lines don't parse, try the full content
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return result

    # Module-level docstring
    if (tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, (ast.Constant, ast.Str))):
        val = tree.body[0].value
        result["docstring"] = val.value if isinstance(val, ast.Constant) else val.s  # type: ignore[attr-defined]

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            result["classes"].append(node.name)
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            result["functions"].append(node.name)

    return result


def _classify_file(filepath: Path, repo_root: Path) -> str:
    """Classify a file into a type category."""
    suffix = filepath.suffix.lower()
    rel_str = str(filepath.relative_to(repo_root)).lower()

    if suffix == ".py":
        if "glue" in rel_str:
            return "glue"
        return "python"
    if suffix == ".sql":
        return "sql"
    if suffix in (".md", ".txt", ".rst"):
        return "markdown"
    if suffix in (".yaml", ".yml"):
        return "yaml"
    if suffix == ".json":
        return "config"
    if suffix in (".cfg", ".ini", ".toml", ".conf"):
        return "config"
    return "other"


def parse_all_files(repo_path: str) -> dict:
    """
    Walk the entire repo tree and extract content/metadata from all file types.

    This is the extended parser used when a KB repo has parse_all=True.
    It skips files already handled by the standard YAML/SQL DAG parser.

    Returns:
        {
            "files": [
                {
                    "path": "relative/path",
                    "type": "python|markdown|config|glue|sql|yaml",
                    "content": "...",
                    "summary": "first 500 chars"
                }
            ]
        }
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        logger.warning("parse_all_files: repo path does not exist: %s", repo_path)
        return {"files": []}

    files: list[dict] = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(repo):
        # Prune skip directories in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for fname in sorted(filenames):
            if file_count >= _MAX_FILES:
                break

            fpath = Path(dirpath) / fname
            suffix = fpath.suffix.lower()

            # Skip binary files
            if suffix in _BINARY_EXTS:
                continue

            # Skip hidden files
            if fname.startswith("."):
                continue

            # Skip files already handled by standard DAG parser
            if suffix in (".yaml", ".yml") and _is_dag_yaml(fpath, repo):
                continue

            # Skip files that are too large
            try:
                fsize = fpath.stat().st_size
                if fsize == 0 or fsize > _MAX_READ_BYTES * 5:
                    continue
            except OSError:
                continue

            file_type = _classify_file(fpath, repo)
            rel_path = str(fpath.relative_to(repo))

            try:
                raw = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Truncate content to max read size
            content = raw[:_MAX_READ_BYTES] if len(raw) > _MAX_READ_BYTES else raw

            entry: dict[str, Any] = {
                "path": rel_path,
                "type": file_type,
                "summary": content[:500],
            }

            if file_type == "python":
                py_info = _extract_python_summary(raw)
                entry["content"] = content
                if py_info["docstring"]:
                    entry["docstring"] = py_info["docstring"]
                if py_info["classes"]:
                    entry["classes"] = py_info["classes"]
                if py_info["functions"]:
                    entry["functions"] = py_info["functions"]

            elif file_type == "glue":
                # Glue scripts: extract both SQL and Python logic
                entry["content"] = content
                py_info = _extract_python_summary(raw)
                if py_info["functions"]:
                    entry["functions"] = py_info["functions"]
                # Try to find embedded SQL strings
                sql_matches = re.findall(r'"""(.*?)"""', raw, re.DOTALL)
                sql_snippets = [m.strip() for m in sql_matches if any(
                    kw in m.upper() for kw in ("SELECT", "INSERT", "CREATE", "DROP", "ALTER", "WITH")
                )]
                if sql_snippets:
                    entry["embedded_sql"] = sql_snippets[:10]

            elif file_type in ("markdown",):
                entry["content"] = content

            elif file_type == "sql":
                entry["content"] = content

            elif file_type in ("yaml", "config"):
                entry["content"] = content
                # For YAML/JSON, try to summarize structure
                if suffix in (".yaml", ".yml"):
                    try:
                        parsed = yaml.safe_load(raw)
                        if isinstance(parsed, dict):
                            entry["top_keys"] = list(parsed.keys())[:20]
                    except Exception:
                        pass
                elif suffix == ".json":
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            entry["top_keys"] = list(parsed.keys())[:20]
                    except Exception:
                        pass
            else:
                entry["content"] = content

            files.append(entry)
            file_count += 1

        if file_count >= _MAX_FILES:
            break

    logger.info("parse_all_files: processed %d files from %s", len(files), repo_path)
    return {"files": files}
