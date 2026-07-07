"""Shared Pydantic models: configuration, results, workflow specs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- config


class SystemConfig(BaseModel):
    """One LANforge system (GUI JSON API + OS shell)."""

    id: str = "default"
    host: str
    port: int = 8080
    protocol: Literal["http", "https"] = "http"
    verify_ssl: bool = False
    username: str = "lanforge"
    password: str = "lanforge"
    ssh_port: int = 22
    ssh_username: str = ""
    ssh_password: str = ""
    ssh_key_file: str | None = None
    timeout_sec: float = 120.0
    connect_timeout_sec: float = 10.0
    retries: int = 3
    retry_backoff_sec: float = 1.0

    @model_validator(mode="after")
    def _default_ssh_credentials(self) -> SystemConfig:
        if not self.ssh_username:
            self.ssh_username = self.username
        if not self.ssh_password:
            self.ssh_password = self.password
        return self

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"


class SafetyConfig(BaseModel):
    read_only: bool = False
    dry_run: bool = False
    require_confirmation: bool = True
    allow_shell: bool = True
    audit_log_path: str = "lanforge-mcp-audit.jsonl"
    extra_destructive_commands: list[str] = Field(default_factory=list)


class ScriptsConfig(BaseModel):
    """Where to find and how to run lanforge-scripts py-scripts."""

    local_path: str | None = None
    remote_path: str = "/home/lanforge/scripts/py-scripts"
    mode: Literal["auto", "local", "remote"] = "auto"
    python_exec: str = "python3"
    default_timeout_sec: float = 600.0


class ReportsConfig(BaseModel):
    output_dir: str = "lanforge-reports"


class AppConfig(BaseModel):
    systems: list[SystemConfig] = Field(default_factory=list)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    scripts: ScriptsConfig = Field(default_factory=ScriptsConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    log_level: str = "INFO"
    log_file: str | None = None


# --------------------------------------------------------------------------- results


class ShellResult(BaseModel):
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool = False


class CommandResult(BaseModel):
    command: str
    params: dict[str, Any]
    ok: bool
    dry_run: bool = False
    status: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    response: Any = None


class ScriptRunInfo(BaseModel):
    run_id: str
    script: str
    args: list[str]
    mode: Literal["local", "remote"]
    state: Literal["running", "finished", "failed", "cancelled"]
    exit_code: int | None = None
    started_at: str
    finished_at: str | None = None
    output_tail: str = ""


# --------------------------------------------------------------------------- workflow


StepAction = Literal[
    "command",  # POST /cli-json/<command>
    "raw",  # POST /cli-json/raw one-line CLI
    "query",  # GET endpoint
    "shell",  # SSH shell command
    "script",  # run a lanforge-scripts py-script
    "wait",  # sleep N seconds
    "wait_for",  # poll an endpoint until a condition holds
    "sample",  # collect endpoint rows every interval for a duration
    "report",  # generate a report from registered data
    "log",  # emit a progress message
]


class Condition(BaseModel):
    """Safe, non-eval condition applied to normalized endpoint rows."""

    field: str
    op: Literal["eq", "ne", "gt", "lt", "ge", "le", "contains", "not_contains"] = "eq"
    value: Any = None
    match: Literal["all", "any"] = "all"


class WorkflowStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action: StepAction
    name: str = ""
    # command / raw
    command: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    line: str = ""
    confirm: bool = False
    # query / wait_for / sample — numeric fields accept "${var}" placeholders
    endpoint: str = ""
    columns: list[str] = Field(default_factory=list)
    eids: list[str] = Field(default_factory=list)
    until: Condition | None = None
    timeout_sec: float | str = 120.0
    interval_sec: float | str = 5.0
    duration_sec: float | str = 60.0
    # shell
    shell: str = ""
    # script
    script: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    # wait
    seconds: float | str = 0.0
    # report
    title: str = ""
    data: Any = None
    # log
    message: str = ""
    # common
    register_as: str = Field(default="", alias="register")
    on_error: Literal["abort", "continue", "retry"] = "abort"
    retries: int = 2


class WorkflowSpec(BaseModel):
    name: str = "workflow"
    description: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStep]


class StepResult(BaseModel):
    index: int
    action: str
    name: str
    ok: bool
    skipped: bool = False
    dry_run: bool = False
    duration_ms: int = 0
    result: Any = None
    error: dict[str, Any] | None = None


class WorkflowResult(BaseModel):
    workflow_id: str
    name: str
    ok: bool
    dry_run: bool = False
    state: Literal["finished", "failed", "cancelled", "running"]
    steps: list[StepResult] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    started_at: str = ""
    finished_at: str | None = None
