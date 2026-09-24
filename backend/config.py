import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    # AI provider: "anthropic" (direct API) or "bedrock" (AWS Bedrock)
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "bedrock")
    BEDROCK_SSO_ENV: str = os.getenv("BEDROCK_SSO_ENV", "np")  # which SSO environment to use for Bedrock
    BEDROCK_REGION: str = os.getenv("BEDROCK_REGION", "us-west-2")
    BEDROCK_MODEL: str = os.getenv("BEDROCK_MODEL", "us.anthropic.claude-opus-4-6-v1")

    # Tiered model strategy: fast model for routing/sub-agents, heavy model for synthesis
    # BEDROCK_MODEL_FAST is used for: principal routing, sub-agent tool calls, classification
    # BEDROCK_MODEL (above) is used for: final synthesis, complex reasoning
    BEDROCK_MODEL_FAST: str = os.getenv("BEDROCK_MODEL_FAST", "us.anthropic.claude-sonnet-4-20250514-v1:0")
    CLAUDE_MODEL_FAST: str = os.getenv("CLAUDE_MODEL_FAST", "claude-sonnet-4-20250514")

    REDSHIFT_MODE: str = os.getenv("REDSHIFT_MODE", "mock")

    # Redshift cluster details
    REDSHIFT_NP_HOST: str = os.getenv(
        "REDSHIFT_NP_HOST",
        "nonprod-redshift-cluster.css1j4dcotkk.us-west-2.redshift.amazonaws.com",
    )
    REDSHIFT_NP_PORT: int = int(os.getenv("REDSHIFT_NP_PORT", "5439"))
    REDSHIFT_NP_DATABASE: str = os.getenv("REDSHIFT_NP_DATABASE", "dev")
    REDSHIFT_NP_CLUSTER_ID: str = os.getenv("REDSHIFT_NP_CLUSTER_ID", "nonprod-redshift-cluster")

    REDSHIFT_PRD_HOST: str = os.getenv(
        "REDSHIFT_PRD_HOST",
        "prod-redshift-cluster.css1j4dcotkk.us-west-2.redshift.amazonaws.com",
    )
    REDSHIFT_PRD_PORT: int = int(os.getenv("REDSHIFT_PRD_PORT", "5439"))
    REDSHIFT_PRD_DATABASE: str = os.getenv("REDSHIFT_PRD_DATABASE", "dev")
    REDSHIFT_PRD_CLUSTER_ID: str = os.getenv("REDSHIFT_PRD_CLUSTER_ID", "prod-redshift-cluster")

    # AWS SSO profiles (match ~/.aws/config)
    AWS_PROFILE_NP: str = os.getenv("AWS_PROFILE_NP", "nonprod")
    AWS_PROFILE_PRD: str = os.getenv("AWS_PROFILE_PRD", "prod")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-west-2")

    # MWAA (Managed Workflows for Apache Airflow) environment names
    MWAA_NP_ENV_NAME: str = os.getenv("MWAA_NP_ENV_NAME", "nonprod-airflow-mwaa")
    MWAA_PRD_ENV_NAME: str = os.getenv("MWAA_PRD_ENV_NAME", "prod-airflow-mwaa")

    # Okta SAML for Redshift (used by DataGrip / redshift_connector)
    OKTA_IDP_HOST: str = os.getenv("OKTA_IDP_HOST", "your-org.okta.com")
    OKTA_APP_ID_NP: str = os.getenv("OKTA_APP_ID_NP", "0oaoa23lch3Gr9uhg5d7")
    OKTA_APP_ID_PRD: str = os.getenv("OKTA_APP_ID_PRD", "0oaoa4mzezdFaZi4v5d7")

    # Okta OIDC for app login (set by IT admin)
    OKTA_CLIENT_ID: str = os.getenv("OKTA_CLIENT_ID", "")
    OKTA_CLIENT_SECRET: str = os.getenv("OKTA_CLIENT_SECRET", "")
    OKTA_ISSUER: str = os.getenv("OKTA_ISSUER", "https://your-org.okta.com/oauth2/default")
    APP_URL: str = os.getenv("APP_URL", "https://genie.example.com")

    # DOMO MCP (dataset search, metadata, schema, SQL query)
    DOMO_DEVELOPER_TOKEN: str = os.getenv("DOMO_DEVELOPER_TOKEN", "")
    DOMO_HOST: str = os.getenv("DOMO_HOST", "your-org.domo.com")

    # Git repo for data platform transforms
    REPO_URL: str = os.getenv("REPO_URL", "")
    REPO_PATH: str = os.getenv("REPO_PATH", "/app/data-repo")          # Workbench (user edits, feature branches)
    REPO_PATH_KB: str = os.getenv("REPO_PATH_KB", "/app/data-repo-kb") # KB builder (read-only, always main)
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # Fallback: explicit user/password (if not using IAM)
    REDSHIFT_NP_USER: str = os.getenv("REDSHIFT_NP_USER", "")
    REDSHIFT_NP_PASSWORD: str = os.getenv("REDSHIFT_NP_PASSWORD", "")
    REDSHIFT_PRD_USER: str = os.getenv("REDSHIFT_PRD_USER", "")
    REDSHIFT_PRD_PASSWORD: str = os.getenv("REDSHIFT_PRD_PASSWORD", "")

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://genie:genie_local@localhost:5432/genie",
    )

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    KNOWLEDGE_DIR: str = os.getenv("KNOWLEDGE_DIR", "knowledge")

    QUERY_TIMEOUT_SECONDS: int = 60
    QUERY_MAX_ROWS: int = 1000


config = Config()
