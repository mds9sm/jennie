GENIE_TOOLS = [
    {
        "name": "search_tables",
        "description": "Search the data catalog for tables matching a keyword. Returns table name, schema, description, and column list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword to match against table names, schemas, and descriptions",
                }
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "search_transforms",
        "description": "Search for transform pipeline configurations matching a keyword. Returns transform name, target table, schedule, and DAG ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword to match against transform names and descriptions",
                }
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_table_detail",
        "description": "Get full details for a specific table including columns, dist/sort keys, row count estimate, and upstream DAG.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Fully qualified table name (schema.table) or just the table name",
                }
            },
            "required": ["table_name"],
        },
    },
    {
        "name": "get_table_lineage",
        "description": "Get upstream and/or downstream dependencies for a table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Table name to trace lineage for",
                },
                "direction": {
                    "type": "string",
                    "enum": ["upstream", "downstream", "both"],
                    "description": "Direction to trace",
                },
            },
            "required": ["table_name"],
        },
    },
    {
        "name": "get_transform_detail",
        "description": "Get full details for a specific transform/DAG including rendered SQL (actual executed query), task-level execution stats (duration per task), run history (success rate, avg duration, failure streaks), and source tables.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dag_id": {
                    "type": "string",
                    "description": "The DAG ID (e.g., TRANSFORM_DAG__foo__bar) or transform name",
                }
            },
            "required": ["dag_id"],
        },
    },
    {
        "name": "get_view_detail",
        "description": "Get the full SQL definition of a Redshift view that defines a business metric or KPI. Returns the CREATE OR REPLACE VIEW SQL, source tables, and DOMO dataset link if available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "view_name": {
                    "type": "string",
                    "description": "The view/metric name (e.g., 'pillar_2_kpi', 'engagement_depth_material_with_country')",
                }
            },
            "required": ["view_name"],
        },
    },
    {
        "name": "glossary_lookup",
        "description": "Look up a business term in the glossary. Returns definition, calculation formula, source table, DAG, and pillar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "Business term to look up (e.g., 'activation rate', 'churn', 'engaged user')",
                }
            },
            "required": ["term"],
        },
    },
    {
        "name": "execute_query",
        "description": "Execute a read-only SQL query against Redshift. Only SELECT and EXPLAIN are allowed. Returns columns and rows.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute (SELECT or EXPLAIN only)",
                },
                "environment": {
                    "type": "string",
                    "enum": ["np", "prd"],
                    "description": "Target environment. Default: np (nonprod)",
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "repo_search",
        "description": "Search code in the locally cloned repos. Grep for patterns across all files — much faster than reading files one by one. Use for finding code patterns, function usage, imports, file I/O, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (text or regex). E.g., 'open(', '/tmp', 'to_csv', 'PythonOperator', 'os.write'",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "File glob to filter (e.g., '*.py', '*.sql', '*.yaml'). Default: all files.",
                },
                "repo": {
                    "type": "string",
                    "description": "Which repo: 'data_platform' (default) or 'gitops'",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "github_file",
        "description": "Read a specific file from a repo. Use repo_search first to find files, then this to read them. Works on locally cloned repos (instant) with GitHub API fallback.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "GitHub repo (e.g., 'your-org/gitops-config' or 'your-org/data-platform-dags')",
                },
                "path": {
                    "type": "string",
                    "description": "File path in the repo",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name (default: main)",
                },
            },
            "required": ["repo", "path"],
        },
    },
    {
        "name": "aws_lookup",
        "description": "Query live AWS resources using SSO read access. Supports: mwaa_environment (env class, config, workers), mwaa_dag_runs (recent runs), s3_list (list objects), cloudwatch_logs (recent log events), glue_jobs (list/describe Glue jobs), lambda_functions (list functions), ecs_services (list ECS services), cloudwatch_metrics (get metric stats). Read-only — uses existing SSO credentials.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "enum": ["mwaa_environment", "mwaa_dag_runs", "s3_list", "cloudwatch_logs", "glue_jobs", "lambda_functions", "ecs_services", "cloudwatch_metrics"],
                    "description": "Which AWS resource to query",
                },
                "environment": {
                    "type": "string",
                    "enum": ["np", "prd"],
                    "description": "Which SSO environment to use",
                },
                "parameters": {
                    "type": "object",
                    "description": "Service-specific parameters (e.g., {dag_id} for mwaa_dag_runs, {bucket, prefix} for s3_list)",
                },
            },
            "required": ["service", "environment"],
        },
    },
    {
        "name": "domo_search",
        "description": "Search DOMO datasets by name. Returns dataset IDs and names. Use this to find which DOMO dashboard datasets exist for a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term (e.g., 'activation', 'cut session', 'engagement')"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "domo_dataset_info",
        "description": "Get metadata and schema for a DOMO dataset — owner, name, row count, column names/types, last updated. Use dataset_id from domo_search or domo_catalog.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "DOMO dataset UUID (from domo_search results or domo_catalog.json)"},
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "domo_dashboards",
        "description": "List DOMO dashboards (executive pages) with card counts. READ-ONLY. Use to find which dashboards exist and what KPIs they show.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "domo_dashboard_detail",
        "description": "Get cards (KPIs, charts, text) on a specific DOMO dashboard. Returns card titles and types. READ-ONLY. Use page_id from domo_dashboards.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "DOMO page/dashboard ID"},
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "domo_query",
        "description": "Execute a SQL query directly against a DOMO dataset. Returns columns and rows. Use for quick lookups when you have a dataset_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "DOMO dataset UUID"},
                "sql": {"type": "string", "description": "SQL query (SELECT only)"},
            },
            "required": ["dataset_id", "sql"],
        },
    },
    {
        "name": "get_event_schema",
        "description": "Get the payload schema for a ProductApp event (from Swagger spec). Returns field names, types, and descriptions. Use this before querying firehose_v3_enriched to know exact SUPER column field names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_name": {"type": "string", "description": "Event name (e.g., CutProjectCompleted, ImageInserted, SearchPerformed)"},
            },
            "required": ["event_name"],
        },
    },
    {
        "name": "search_events",
        "description": "Search ProductApp event types by keyword. Returns matching event names and their field counts. Use to find which events exist for a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword (e.g., 'cut', 'search', 'image', 'subscription')"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "analyze_domo_dataset",
        "description": "Analyze a DOMO S3 dataset (pre-aggregated executive metric data). Reads CSV/TSV files from prod-bi-export S3 bucket and runs aggregations locally — NO Redshift load. Use this for metric questions instead of querying Redshift directly. Returns summary stats, column info, and aggregated data suitable for charts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Metric/view name from the DOMO catalog (e.g., 'engagement_depth_wmq', 'pillar_2_north_star_metrics')",
                },
                "query": {
                    "type": "string",
                    "description": "Optional SQL query to run against the dataset using DuckDB. The data is available as a table named 'data'. E.g.: SELECT event_date, SUM(users) FROM data GROUP BY 1 ORDER BY 1. If omitted, returns column info + sample rows + basic stats.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default: 100)",
                },
            },
            "required": ["metric_name"],
        },
    },
    {
        "name": "search_dq_findings",
        "description": "Search the events DQ findings table for the ProductApp events pipeline. Use for questions like 'why did Desktop drop yesterday', 'what broke last night', 'show me iOS anomalies this week', 'are there any cross-stage drift findings', 'platform regressions after the latest release'. Findings come from the nightly events_dq__nightly_analyze DAG and cover stage drift, DoW/Prophet anomalies, new versions, version rollover drops, and platform imbalance. Returns the most relevant findings ranked by severity and recency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days back to search (1-90, default 7)"},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Filter by severity",
                },
                "kind": {
                    "type": "string",
                    "description": "Filter by finding kind (stage_drift, dow_anomaly, prophet_anomaly, new_version, version_rollover_drop, platform_imbalance, dim_staleness, dim_count_drop, dim_key_nulls, dq_sync_failure)",
                },
                "platform": {"type": "string", "description": "Filter by client_platform_name (e.g., 'IOS', 'ANDROID', 'WINDOWS', 'MACOS')"},
                "event_name": {"type": "string", "description": "Filter by event name (e.g., 'CutMatCompleted', 'ImageInserted')"},
                "limit": {"type": "integer", "description": "Max findings to return (default 50)"},
            },
        },
    },
]
