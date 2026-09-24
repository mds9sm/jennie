from pydantic import BaseModel, Field


class ChatAttachment(BaseModel):
    filename: str
    content: str = ""  # extracted text content (for documents)
    is_image: bool = False
    media_type: str = ""  # e.g., image/png
    base64: str = ""  # base64-encoded image data

class ChatRequest(BaseModel):
    message: str
    pillar: str | None = None
    environment: str = "np"
    session_id: str | None = None
    conversation_history: list[dict] = Field(default_factory=list)
    attachments: list[ChatAttachment] = Field(default_factory=list)


class SQLGenerateRequest(BaseModel):
    question: str
    pillar: str | None = None
    environment: str = "np"


class SQLExecuteRequest(BaseModel):
    sql: str
    environment: str = "np"
    timeout_seconds: int = 60
    max_rows: int = 1000
    session_id: str | None = None


class SQLExecuteResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    execution_time_ms: int
    environment: str
    truncated: bool
    query_id: str


class SQLOptimizeRequest(BaseModel):
    sql: str
    pillar: str | None = None


class PipelineGenerateRequest(BaseModel):
    description: str
    pillar: str | None = None


class PipelineGenerateResponse(BaseModel):
    yaml_config: str
    sql_files: dict[str, str]
    explanation: str


class ImpactAnalyzeRequest(BaseModel):
    change_description: str
    pillar: str | None = None


class GlossaryCorrectionRequest(BaseModel):
    term: str
    correction: str
    submitted_by: str = "local-dev"
