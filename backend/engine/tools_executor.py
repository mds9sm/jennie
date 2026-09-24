"""
Tool executor — pure tool dispatch, shared by agent runner and MCP server.

Extracted from engine/agents/runner.py so that the MCP server can call
tools without importing the full agent runner (which has Claude/Bedrock deps).
"""

import asyncio
import logging

from catalog.loader import KnowledgeBase
from catalog.search import search_tables, search_transforms, get_table_detail, get_transform_detail
from catalog.lineage import get_lineage
from config import config

logger = logging.getLogger("genie.tools")


async def execute_tool(tool_name: str, tool_input: dict, kb: KnowledgeBase) -> dict:
    """Execute a data tool by name. Shared by agent runner and MCP server."""
    if tool_name == "search_tables":
        try:
            from catalog.search import search_tables_hybrid
            return await search_tables_hybrid(kb, tool_input["keyword"])
        except Exception:
            return search_tables(kb, tool_input["keyword"])

    elif tool_name == "search_transforms":
        return search_transforms(kb, tool_input["keyword"])

    elif tool_name == "get_table_detail":
        return get_table_detail(kb, tool_input["table_name"])

    elif tool_name == "get_table_lineage":
        return get_lineage(kb, tool_input["table_name"], tool_input.get("direction", "both"))

    elif tool_name == "get_transform_detail":
        return get_transform_detail(kb, tool_input["dag_id"])

    elif tool_name == "get_view_detail":
        detail = kb.get_view_detail(tool_input["view_name"])
        view_name = tool_input["view_name"]
        if not detail:
            from rapidfuzz import fuzz, process
            names = [m["name"] for m in kb.metrics]
            if names:
                matches = process.extract(view_name, names, scorer=fuzz.WRatio, limit=1, score_cutoff=50)
                if matches:
                    detail = kb.get_view_detail(matches[0][0])
                    view_name = matches[0][0]
        if not detail:
            return {"error": f"View '{tool_input['view_name']}' not found"}
        for domo_entry in getattr(kb, "domo_catalog", []):
            if domo_entry.get("name", "").lower() == view_name.lower():
                if domo_entry.get("s3_metadata"):
                    detail["s3_metadata"] = domo_entry["s3_metadata"]
                if domo_entry.get("pillar"):
                    detail["pillar"] = domo_entry["pillar"]
                if domo_entry.get("metric_type"):
                    detail["metric_type"] = domo_entry["metric_type"]
                if domo_entry.get("domo_dataset_id"):
                    detail["domo_dataset_id"] = domo_entry["domo_dataset_id"]
                break
        return detail

    elif tool_name == "glossary_lookup":
        from catalog.search import search_glossary
        results = search_glossary(kb, tool_input["term"])
        if not results:
            return {"error": f"No glossary entry for '{tool_input['term']}'"}
        return results[0] if len(results) == 1 else {"matches": results}

    elif tool_name == "execute_query":
        try:
            from connectors.redshift import _direct_creds, execute_real_query
            from connectors.mock_redshift import execute_mock_query
            env = tool_input.get("environment", "np")
            sql = tool_input["sql"]
            if _direct_creds.get(env) or config.REDSHIFT_MODE != "mock":
                result = await execute_real_query(sql, env, config.QUERY_MAX_ROWS)
            else:
                result = await execute_mock_query(sql, env, config.QUERY_MAX_ROWS)
            result["sql"] = sql
            return result
        except Exception as e:
            return {"error": str(e)}

    elif tool_name == "repo_search":
        return await _execute_repo_search(tool_input)

    elif tool_name == "github_file":
        return await _execute_github_file(tool_input)

    elif tool_name == "aws_lookup":
        return await _execute_aws_lookup(tool_input)

    elif tool_name == "analyze_domo_dataset":
        return await _execute_domo_analysis(tool_input, kb)

    elif tool_name == "domo_search":
        from connectors.domo_client import search_datasets
        return await asyncio.to_thread(search_datasets, tool_input.get("query", ""))

    elif tool_name == "domo_dataset_info":
        from connectors.domo_client import get_dataset_metadata, get_dataset_schema
        meta = await asyncio.to_thread(get_dataset_metadata, tool_input["dataset_id"])
        schema = await asyncio.to_thread(get_dataset_schema, tool_input["dataset_id"])
        if isinstance(meta, dict) and "error" not in meta and isinstance(schema, dict) and "error" not in schema:
            meta["columns"] = schema.get("columns", [])
        return meta

    elif tool_name == "domo_query":
        from connectors.domo_client import query_dataset
        return await asyncio.to_thread(query_dataset, tool_input["dataset_id"], tool_input["sql"])

    elif tool_name == "domo_dashboards":
        from connectors.domo_client import list_dashboards
        return await asyncio.to_thread(list_dashboards)

    elif tool_name == "domo_dashboard_detail":
        from connectors.domo_client import get_dashboard_detail
        return await asyncio.to_thread(get_dashboard_detail, tool_input["page_id"])

    elif tool_name == "get_event_schema":
        from catalog_engine.swagger_parser import get_event_schema
        result = get_event_schema(tool_input["event_name"], "knowledge")
        if result:
            return result
        from catalog_engine.swagger_parser import search_events
        matches = search_events(tool_input["event_name"], "knowledge", limit=3)
        if matches:
            return {
                "error": f"Event '{tool_input['event_name']}' not found. Did you mean: {', '.join(m['event_name'] for m in matches)}?",
                "suggestions": matches,
            }
        return {"error": f"Event '{tool_input['event_name']}' not found. Run KB build to fetch Swagger event schemas."}

    elif tool_name == "search_events":
        from catalog_engine.swagger_parser import search_events
        results = search_events(tool_input["keyword"], "knowledge")
        return {"keyword": tool_input["keyword"], "results": results, "count": len(results)}

    elif tool_name == "search_dq_findings":
        return await _execute_search_dq_findings(tool_input)

    elif tool_name.startswith("kb_"):
        from engine.agents.kb_agent import execute_kb_tool
        return await execute_kb_tool(tool_name, tool_input, kb)

    elif tool_name.startswith("github__"):
        from engine.mcp_bridge import call_mcp_tool
        return await call_mcp_tool(tool_name, tool_input)

    return {"error": f"Unknown tool: {tool_name}"}


async def _execute_search_dq_findings(tool_input: dict) -> dict:
    """Query np_dw.analytics.events_dq_findings for recent anomalies/drift findings."""
    from connectors.redshift import execute_real_query

    days = int(tool_input.get("days") or 7)
    days = max(1, min(days, 90))
    limit = int(tool_input.get("limit") or 50)
    limit = max(1, min(limit, 500))

    where = [f"event_date >= CURRENT_DATE - {days}"]
    severity = tool_input.get("severity")
    if severity in ("critical", "warning", "info"):
        where.append(f"severity = '{severity}'")
    for col, key in (("kind", "kind"), ("platform", "platform"), ("event_name", "event_name")):
        val = tool_input.get(key)
        if val:
            safe = str(val).replace("'", "")
            where.append(f"{col} = '{safe}'")

    sql = f"""
        SELECT event_date::VARCHAR AS event_date, severity, kind, stage,
               event_name, platform, client_version,
               observed_value, expected_low, expected_high, z_score, narrative
        FROM np_dw.analytics.events_dq_findings
        WHERE {' AND '.join(where)}
        ORDER BY
            event_date DESC,
            CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            kind
        LIMIT {limit}
    """

    result = await execute_real_query(sql, environment="np", max_rows=limit)
    if "error" in result:
        return {"error": result["error"], "findings": [], "count": 0}

    findings = []
    for row in result["rows"]:
        findings.append(dict(zip(result["columns"], row)))

    return {
        "findings": findings,
        "count": len(findings),
        "filters": {k: v for k, v in tool_input.items() if v is not None},
    }


async def _execute_repo_search(tool_input: dict) -> dict:
    """Grep for patterns in locally cloned repos — instant, no API calls."""
    import subprocess
    from pathlib import Path

    pattern = tool_input.get("pattern", "")
    file_pattern = tool_input.get("file_pattern", "")
    repo = tool_input.get("repo", "data_platform")

    if not pattern:
        return {"error": "pattern required"}

    repo_paths = {
        "data_platform": Path(config.REPO_PATH_KB) if Path(config.REPO_PATH_KB).exists() else Path(config.REPO_PATH),
        "gitops": Path("/app/data-repo-kb/gitops_config"),
    }
    repo_path = repo_paths.get(repo)
    if not repo_path or not repo_path.exists():
        return {"error": f"Repo '{repo}' not cloned locally"}

    def _search():
        cmd = ["grep", "-rn", "--include", file_pattern or "*", "-l", pattern, str(repo_path)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            matching_files = [f for f in result.stdout.strip().split("\n") if f][:30]

            if not matching_files:
                return {"pattern": pattern, "matches": [], "count": 0}

            cmd2 = ["grep", "-rn", "--include", file_pattern or "*", "-C", "1", pattern, str(repo_path)]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
            lines = result2.stdout.strip().split("\n")[:100]

            repo_str = str(repo_path) + "/"
            matches = []
            for line in lines:
                if line.startswith(repo_str):
                    line = line[len(repo_str):]
                matches.append(line)

            return {
                "pattern": pattern,
                "repo": repo,
                "file_count": len(matching_files),
                "files": [f.replace(repo_str, "") for f in matching_files],
                "matches": matches,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Search timed out (pattern too broad?)"}
        except Exception as e:
            return {"error": f"Search failed: {str(e)[:200]}"}

    return await asyncio.to_thread(_search)


async def _execute_github_file(tool_input: dict) -> dict:
    """Read a file — local clone first (instant), GitHub API as fallback."""
    import requests as http_requests
    from pathlib import Path

    repo = tool_input.get("repo", "")
    path = tool_input.get("path", "")
    branch = tool_input.get("branch", "main")

    if not repo or not path:
        return {"error": "repo and path required"}

    local_paths = {
        "your-org/data-platform-dags": [
            Path(config.REPO_PATH_KB),
            Path(config.REPO_PATH),
        ],
    }

    for base_path in [Path("/app/data-repo-kb")]:
        if base_path.is_dir():
            for child in base_path.iterdir():
                if child.is_dir() and (child / ".git").exists():
                    repo_short = repo.split("/")[-1].lower()
                    if repo_short in child.name.lower():
                        local_paths.setdefault(repo, []).append(child)

    for local_root in local_paths.get(repo, []):
        local_file = local_root / path
        if local_file.exists() and local_file.is_file():
            try:
                content = local_file.read_text(errors="replace")
                if len(content) > 10000:
                    content = content[:10000] + f"\n\n... (truncated, {len(content)} total chars)"
                return {"repo": repo, "path": path, "source": "local_clone", "content": content}
            except Exception:
                pass

    token = config.GITHUB_TOKEN
    if not token:
        return {"error": "File not found locally and no GitHub token configured"}

    def _fetch():
        url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
        resp = http_requests.get(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3.raw",
        }, timeout=10)
        if resp.status_code == 200:
            content = resp.text
            if len(content) > 10000:
                content = content[:10000] + f"\n\n... (truncated, {len(resp.text)} total chars)"
            return {"repo": repo, "path": path, "source": "github_api", "content": content}
        elif resp.status_code == 404:
            return {"error": f"File not found: {repo}/{path} (branch: {branch})"}
        else:
            return {"error": f"GitHub API error {resp.status_code}: {resp.text[:200]}"}

    return await asyncio.to_thread(_fetch)


async def _execute_domo_analysis(tool_input: dict, kb) -> dict:
    """Analyze DOMO S3 dataset locally using DuckDB — no Redshift load."""
    metric_name = tool_input.get("metric_name", "")
    query = tool_input.get("query", "")
    limit = tool_input.get("limit", 100)

    if not metric_name:
        return {"error": "metric_name required"}

    domo_catalog = getattr(kb, "domo_catalog", [])
    metric = None
    for m in domo_catalog:
        if m.get("name", "").lower() == metric_name.lower():
            metric = m
            break

    if not metric:
        from rapidfuzz import fuzz, process
        names = [m["name"] for m in domo_catalog]
        if names:
            matches = process.extract(metric_name, names, scorer=fuzz.WRatio, limit=1, score_cutoff=50)
            if matches:
                for m in domo_catalog:
                    if m["name"] == matches[0][0]:
                        metric = m
                        break

    if not metric:
        return {"error": f"Metric '{metric_name}' not found in DOMO catalog. Available: {', '.join(m['name'] for m in domo_catalog[:10])}"}

    s3_path = metric.get("s3_path", "")
    if not s3_path:
        return {"error": f"Metric '{metric_name}' has no S3 path — not a DOMO-exported dataset",
                "metric_info": {k: v for k, v in metric.items() if k != "s3_metadata"}}

    def _analyze():
        try:
            import duckdb
        except ImportError:
            return {"error": "DuckDB not installed — cannot analyze S3 data locally"}

        try:
            from connectors.credential_store import credential_store
            import boto3

            s3_client = None
            for env in ("np", "prd"):
                for sid, session in credential_store._sessions.items():
                    creds = session.get_credentials(env)
                    if creds:
                        s3_client = boto3.client(
                            "s3",
                            aws_access_key_id=creds.access_key_id,
                            aws_secret_access_key=creds.secret_access_key,
                            aws_session_token=creds.session_token,
                            region_name="us-west-2",
                        )
                        break
                if s3_client:
                    break

            if not s3_client:
                return {"error": "No SSO credentials for S3. Connect SSO in Settings → Connection first."}

            bucket = s3_path.replace("s3://", "").split("/")[0]
            prefix = "/".join(s3_path.replace("s3://", "").split("/")[1:])

            resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=50)
            objects = resp.get("Contents", [])
            if not objects:
                return {"error": f"No files at {s3_path}"}

            objects.sort(key=lambda o: o["Size"], reverse=True)

            max_bytes = 50 * 1024 * 1024
            total_read = 0
            all_data = []

            for obj in objects:
                if total_read >= max_bytes:
                    break
                if obj["Size"] < 100:
                    continue
                try:
                    s3_resp = s3_client.get_object(Bucket=bucket, Key=obj["Key"])
                    body = s3_resp["Body"].read()
                    total_read += len(body)
                    text = body.decode("utf-8", errors="replace")
                    all_data.append(text)
                except Exception:
                    continue

            if not all_data:
                return {"error": "Could not read any S3 files"}

            combined = "\n".join(all_data)
            first_line = combined.split("\n")[0]
            delimiter = "\t" if "\t" in first_line else "|" if "|" in first_line else ","

            conn = duckdb.connect(":memory:")
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
            tmp.write(combined)
            tmp.close()

            try:
                conn.execute(f"""
                    CREATE TABLE data AS
                    SELECT * FROM read_csv('{tmp.name}',
                        delim='{delimiter}', header=true,
                        ignore_errors=true, auto_detect=true
                    )
                """)

                schema = conn.execute("DESCRIBE data").fetchall()
                columns = [{"name": r[0], "type": r[1]} for r in schema]
                row_count = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]

                result = {
                    "metric_name": metric["name"],
                    "s3_path": s3_path,
                    "files_read": min(len(objects), 50),
                    "total_size_mb": round(total_read / (1024 * 1024), 1),
                    "columns": columns,
                    "row_count": row_count,
                }

                if query:
                    try:
                        qr = conn.execute(f"{query} LIMIT {limit}").fetchall()
                        col_names = [d[0] for d in conn.description]
                        result["query_columns"] = col_names
                        result["query_rows"] = [list(r) for r in qr]
                        result["query_row_count"] = len(qr)
                    except Exception as qe:
                        result["query_error"] = str(qe)[:300]
                else:
                    sample = conn.execute("SELECT * FROM data LIMIT 5").fetchall()
                    col_names = [d[0] for d in conn.description]
                    result["sample_columns"] = col_names
                    result["sample_rows"] = [list(r) for r in sample]
                    for col in columns:
                        if "date" in col["name"].lower() or col["type"] in ("DATE", "TIMESTAMP"):
                            try:
                                dr = conn.execute(f"SELECT MIN(\"{col['name']}\"), MAX(\"{col['name']}\") FROM data").fetchone()
                                result["date_range"] = {"column": col["name"], "min": str(dr[0]), "max": str(dr[1])}
                            except Exception:
                                pass
                            break

                result["pillar"] = metric.get("pillar", "")
                result["metric_type"] = metric.get("metric_type", "")
                result["domo_dataset_id"] = metric.get("domo_dataset_id", "")
                result["source_tables"] = metric.get("source_tables", [])
                return result

            finally:
                os.unlink(tmp.name)
                conn.close()

        except Exception as e:
            return {"error": f"DOMO analysis failed: {str(e)[:300]}"}

    return await asyncio.to_thread(_analyze)


async def _execute_aws_lookup(tool_input: dict) -> dict:
    """Execute a live read-only AWS API call using SSO credentials."""
    service = tool_input.get("service", "")
    environment = tool_input.get("environment", "np")
    params = tool_input.get("parameters", {})

    try:
        from connectors.credential_store import credential_store
        import boto3

        creds = None
        for sid, session in credential_store._sessions.items():
            creds = session.get_credentials(environment)
            if creds:
                break

        if not creds:
            return {"error": f"No SSO credentials for {environment}. Connect SSO first in Settings → Connection."}

        boto_session = boto3.Session(
            aws_access_key_id=creds.access_key_id,
            aws_secret_access_key=creds.secret_access_key,
            aws_session_token=creds.session_token,
            region_name="us-west-2",
        )

        if service == "mwaa_environment":
            def _fetch():
                mwaa = boto_session.client("mwaa")
                env_names = {
                    "np": "nonprod-airflow-mwaa",
                    "prd": "prod-airflow-mwaa",
                }
                env_name = params.get("env_name") or env_names.get(environment, "")
                resp = mwaa.get_environment(Name=env_name)
                env = resp.get("Environment", {})
                return {
                    "name": env.get("Name"), "status": env.get("Status"),
                    "environment_class": env.get("EnvironmentClass"),
                    "airflow_version": env.get("AirflowVersion"),
                    "max_workers": env.get("MaxWorkers"),
                    "dag_s3_path": env.get("DagS3Path"),
                }
            return await asyncio.to_thread(_fetch)

        elif service == "mwaa_dag_runs":
            dag_id = params.get("dag_id", "")
            if not dag_id:
                return {"error": "dag_id parameter required"}
            def _fetch():
                from catalog_engine.mwaa_fetcher import _get_mwaa_env_name, _get_session_info, _call_api
                from urllib.parse import quote as url_quote
                env_name = _get_mwaa_env_name(environment)
                host, session_cookie = _get_session_info(boto_session, env_name)
                if not host:
                    return {"error": "Could not authenticate to MWAA"}
                encoded = url_quote(dag_id, safe="")
                url = f"https://{host}/api/v1/dags/{encoded}/dagRuns?order_by=-execution_date&limit=10"
                resp = _call_api(host, session_cookie, url)
                if not resp:
                    return {"error": f"No data for DAG {dag_id}"}
                runs = resp.get("dag_runs", [])
                return {"dag_id": dag_id, "runs": [
                    {"state": r.get("state"), "date": r.get("execution_date"), "duration": r.get("duration")}
                    for r in runs[:10]
                ]}
            return await asyncio.to_thread(_fetch)

        elif service == "s3_list":
            bucket = params.get("bucket", "")
            prefix = params.get("prefix", "")
            if not bucket:
                return {"error": "bucket parameter required"}
            def _fetch():
                s3 = boto_session.client("s3")
                resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=20)
                return {"bucket": bucket, "prefix": prefix, "objects": [
                    {"key": o["Key"], "size": o["Size"], "modified": str(o["LastModified"])}
                    for o in resp.get("Contents", [])
                ]}
            return await asyncio.to_thread(_fetch)

        elif service == "cloudwatch_logs":
            log_group = params.get("log_group", "")
            filter_pattern = params.get("filter_pattern", "")
            limit = params.get("limit", 20)
            if not log_group:
                return {"error": "log_group parameter required"}
            def _fetch():
                logs = boto_session.client("logs")
                kwargs = {"logGroupName": log_group, "limit": min(limit, 50), "interleaved": True}
                if filter_pattern:
                    kwargs["filterPattern"] = filter_pattern
                resp = logs.filter_log_events(**kwargs)
                return {"log_group": log_group, "events": [
                    {"timestamp": str(e.get("timestamp", "")), "message": e.get("message", "")[:500]}
                    for e in resp.get("events", [])[:50]
                ]}
            return await asyncio.to_thread(_fetch)

        elif service == "glue_jobs":
            job_name = params.get("job_name", "")
            def _fetch():
                glue = boto_session.client("glue")
                if job_name:
                    resp = glue.get_job(JobName=job_name)
                    job = resp.get("Job", {})
                    runs_resp = glue.get_job_runs(JobName=job_name, MaxResults=5)
                    return {
                        "job": {"name": job.get("Name"), "command": job.get("Command", {}).get("ScriptLocation")},
                        "recent_runs": [{"id": r.get("Id"), "state": r.get("JobRunState"),
                                        "started": str(r.get("StartedOn", "")),
                                        "duration": r.get("ExecutionTime")}
                                       for r in runs_resp.get("JobRuns", [])]
                    }
                else:
                    resp = glue.get_jobs(MaxResults=50)
                    return {"jobs": [{"name": j.get("Name")} for j in resp.get("Jobs", [])]}
            return await asyncio.to_thread(_fetch)

        elif service == "lambda_functions":
            function_name = params.get("function_name", "")
            def _fetch():
                lam = boto_session.client("lambda")
                if function_name:
                    resp = lam.get_function(FunctionName=function_name)
                    c = resp.get("Configuration", {})
                    return {"function": {"name": c.get("FunctionName"), "runtime": c.get("Runtime"),
                                        "memory": c.get("MemorySize"), "timeout": c.get("Timeout")}}
                else:
                    resp = lam.list_functions(MaxItems=50)
                    return {"functions": [{"name": f.get("FunctionName"), "runtime": f.get("Runtime")}
                                         for f in resp.get("Functions", [])]}
            return await asyncio.to_thread(_fetch)

        elif service == "ecs_services":
            cluster = params.get("cluster", "")
            def _fetch():
                ecs = boto_session.client("ecs")
                if cluster:
                    resp = ecs.list_services(cluster=cluster, maxResults=50)
                    arns = resp.get("serviceArns", [])
                    if arns:
                        desc = ecs.describe_services(cluster=cluster, services=arns[:10])
                        return {"cluster": cluster, "services": [
                            {"name": s.get("serviceName"), "status": s.get("status"),
                             "desired": s.get("desiredCount"), "running": s.get("runningCount")}
                            for s in desc.get("services", [])
                        ]}
                    return {"cluster": cluster, "services": []}
                else:
                    resp = ecs.list_clusters(maxResults=20)
                    return {"clusters": [a.split("/")[-1] for a in resp.get("clusterArns", [])]}
            return await asyncio.to_thread(_fetch)

        elif service == "cloudwatch_metrics":
            namespace = params.get("namespace", "")
            metric_name = params.get("metric_name", "")
            dimensions = params.get("dimensions", [])
            if not namespace or not metric_name:
                return {"error": "namespace and metric_name required"}
            def _fetch():
                from datetime import datetime, timedelta, timezone
                cw = boto_session.client("cloudwatch")
                end = datetime.now(timezone.utc)
                start = end - timedelta(hours=params.get("hours", 24))
                resp = cw.get_metric_statistics(
                    Namespace=namespace, MetricName=metric_name,
                    Dimensions=[{"Name": d["name"], "Value": d["value"]} for d in dimensions] if dimensions else [],
                    StartTime=start, EndTime=end,
                    Period=params.get("period", 3600),
                    Statistics=["Average", "Maximum", "Sum"],
                )
                return {"namespace": namespace, "metric": metric_name, "datapoints": [
                    {"timestamp": str(d["Timestamp"]), "average": d.get("Average"), "sum": d.get("Sum")}
                    for d in sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
                ]}
            return await asyncio.to_thread(_fetch)

        else:
            return {"error": f"Unknown AWS service: {service}"}

    except Exception as e:
        return {"error": f"AWS lookup failed: {str(e)[:300]}"}
