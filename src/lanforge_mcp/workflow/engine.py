"""Layer 5 — the workflow engine.

Executes a :class:`~lanforge_mcp.models.WorkflowSpec`: an ordered list of steps
(command / raw / query / shell / script / wait / wait_for / sample / report /
log) with ``${variable}`` substitution, per-step output capture (``register``),
error policy (abort / continue / retry), dry-run of the whole plan, progress
callbacks, and cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from ..api.json_api import JsonApi
from ..cliwrap.executor import ShellExecutor
from ..errors import LANforgeMCPError, WorkflowError
from ..models import (
    Condition,
    StepResult,
    WorkflowResult,
    WorkflowSpec,
    WorkflowStep,
)
from ..reports.engine import ReportEngine
from ..scripts.runner import ScriptRunner

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\$\{([a-zA-Z_][\w.\[\]]*)\}")

ProgressCallback = Callable[[int, int, str], Coroutine[Any, Any, None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lookup(context: dict[str, Any], expr: str) -> Any:
    """Resolve a dotted/indexed path like ``stats.rows[0].rx_rate``."""
    token_re = re.compile(r"([\w-]+)|\[(\d+)\]")
    value: Any = context
    for name, index in token_re.findall(expr):
        if name:
            if not isinstance(value, dict) or name not in value:
                raise WorkflowError(f"Variable path '${{{expr}}}' not found at '{name}'.")
            value = value[name]
        else:
            i = int(index)
            if not isinstance(value, list) or i >= len(value):
                raise WorkflowError(f"Variable path '${{{expr}}}' index [{i}] out of range.")
            value = value[i]
    return value


def substitute(value: Any, context: dict[str, Any]) -> Any:
    """Recursively substitute ``${var}`` in strings; whole-string refs keep type."""
    if isinstance(value, str):
        whole = _VAR_RE.fullmatch(value.strip())
        if whole:
            return _lookup(context, whole.group(1))
        return _VAR_RE.sub(lambda m: str(_lookup(context, m.group(1))), value)
    if isinstance(value, dict):
        return {k: substitute(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, context) for v in value]
    return value


def resolve_number(value: float | str, context: dict[str, Any], what: str) -> float:
    """Resolve a numeric step field that may be a ``${var}`` placeholder."""
    resolved = substitute(value, context)
    try:
        return float(resolved)
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"Step field '{what}' is not numeric: {resolved!r}") from exc


def check_condition(rows: list[dict[str, Any]], cond: Condition) -> bool:
    """Apply a safe field/op/value condition across normalized rows."""
    if not rows:
        return False

    def one(row: dict[str, Any]) -> bool:
        actual = row.get(cond.field)
        expected = cond.value
        # Numeric comparison when both sides parse as numbers.
        try:
            a, e = float(actual), float(expected)  # type: ignore[arg-type]
            actual, expected = a, e
        except (TypeError, ValueError):
            actual, expected = str(actual), str(expected)
        match cond.op:
            case "eq":
                return actual == expected
            case "ne":
                return actual != expected
            case "gt":
                return actual > expected
            case "lt":
                return actual < expected
            case "ge":
                return actual >= expected
            case "le":
                return actual <= expected
            case "contains":
                return str(expected) in str(actual)
            case "not_contains":
                return str(expected) not in str(actual)
        return False

    results = [one(r) for r in rows]
    return all(results) if cond.match == "all" else any(results)


class WorkflowEngine:
    def __init__(
        self,
        api: JsonApi,
        shell: ShellExecutor,
        scripts: ScriptRunner,
        reports: ReportEngine,
        system_id: str = "",
    ):
        self.api = api
        self.shell = shell
        self.scripts = scripts
        self.reports = reports
        self.system_id = system_id
        self._running: dict[str, asyncio.Task] = {}
        self._results: dict[str, WorkflowResult] = {}

    # ---------------------------------------------------------------- public

    async def run(
        self,
        spec: WorkflowSpec,
        *,
        dry_run: bool = False,
        background: bool = False,
        progress: ProgressCallback | None = None,
    ) -> WorkflowResult:
        workflow_id = uuid.uuid4().hex[:12]
        result = WorkflowResult(
            workflow_id=workflow_id,
            name=spec.name,
            ok=False,
            dry_run=dry_run,
            state="running",
            started_at=_now(),
            variables=dict(spec.variables),
        )
        self._results[workflow_id] = result
        if background:
            self._running[workflow_id] = asyncio.ensure_future(
                self._execute(spec, result, dry_run, progress)
            )
            return result
        await self._execute(spec, result, dry_run, progress)
        return result

    def status(self, workflow_id: str) -> WorkflowResult:
        if workflow_id not in self._results:
            raise WorkflowError(f"Unknown workflow_id '{workflow_id}'.")
        return self._results[workflow_id]

    async def cancel(self, workflow_id: str) -> WorkflowResult:
        task = self._running.get(workflow_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        result = self.status(workflow_id)
        if result.state == "running":
            result.state = "cancelled"
            result.finished_at = _now()
        return result

    # -------------------------------------------------------------- internal

    async def _execute(
        self,
        spec: WorkflowSpec,
        result: WorkflowResult,
        dry_run: bool,
        progress: ProgressCallback | None,
    ) -> None:
        context: dict[str, Any] = dict(spec.variables)
        total = len(spec.steps)
        try:
            for index, step in enumerate(spec.steps):
                if progress is not None:
                    await progress(index, total, step.name or step.action)
                step_result = await self._run_step_with_policy(index, step, context, dry_run)
                result.steps.append(step_result)
                if step_result.ok and step.register_as:
                    context[step.register_as] = step_result.result
                if not step_result.ok and step.on_error == "abort":
                    result.state = "failed"
                    result.finished_at = _now()
                    return
            result.ok = all(s.ok or s.skipped for s in result.steps)
            result.state = "finished"
        except asyncio.CancelledError:
            result.state = "cancelled"
            raise
        finally:
            result.variables = {
                k: v for k, v in context.items() if isinstance(v, (str, int, float, bool))
            }
            if result.finished_at is None:
                result.finished_at = _now()

    async def _run_step_with_policy(
        self, index: int, step: WorkflowStep, context: dict[str, Any], dry_run: bool
    ) -> StepResult:
        attempts = 1 + (step.retries if step.on_error == "retry" else 0)
        last_error: dict[str, Any] | None = None
        started = time.monotonic()
        for attempt in range(attempts):
            try:
                value = await self._dispatch(step, context, dry_run)
                return StepResult(
                    index=index,
                    action=step.action,
                    name=step.name or step.action,
                    ok=True,
                    dry_run=dry_run,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    result=value,
                )
            except LANforgeMCPError as exc:
                last_error = exc.to_dict()
                logger.warning("workflow step %d (%s) attempt %d failed: %s",
                               index, step.action, attempt + 1, exc.message)
                if attempt < attempts - 1:
                    await asyncio.sleep(min(2**attempt, 10))
        return StepResult(
            index=index,
            action=step.action,
            name=step.name or step.action,
            ok=False,
            skipped=step.on_error == "continue",
            dry_run=dry_run,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=last_error,
        )

    async def _dispatch(self, step: WorkflowStep, context: dict[str, Any], dry_run: bool) -> Any:
        match step.action:
            case "command":
                params = substitute(step.params, context)
                if dry_run:
                    return {"would_run": f"/cli-json/{step.command}", "params": params}
                res = await self.api.command(
                    substitute(step.command, context), params,
                    confirm=step.confirm, system_id=self.system_id,
                )
                if not res.ok:
                    raise WorkflowError(
                        f"Command '{step.command}' failed: {'; '.join(res.errors) or res.status}",
                        details={"response": res.response},
                    )
                return res.model_dump()
            case "raw":
                line = substitute(step.line, context)
                if dry_run:
                    return {"would_run": "/cli-json/raw", "cmd": line}
                res = await self.api.raw(line, confirm=step.confirm, system_id=self.system_id)
                return res.model_dump()
            case "query":
                if dry_run:
                    return {"would_query": step.endpoint}
                q = await self.api.query(
                    substitute(step.endpoint, context),
                    columns=step.columns or None,
                    eids=substitute(step.eids, context) or None,
                )
                return {"rows": q["rows"], "row_count": q["row_count"]}
            case "shell":
                cmd = substitute(step.shell, context)
                if dry_run:
                    return {"would_shell": cmd}
                shell_res = await self.shell.run(
                    cmd,
                    timeout=resolve_number(step.timeout_sec, context, "timeout_sec"),
                    confirm=step.confirm,
                    system_id=self.system_id,
                )
                if shell_res.exit_code != 0:
                    raise WorkflowError(
                        f"Shell command exited {shell_res.exit_code}: {shell_res.stderr[:300]}",
                        details={"stdout": shell_res.stdout[-1000:]},
                    )
                return shell_res.model_dump()
            case "script":
                args = substitute(step.args, context)
                if dry_run:
                    return {"would_script": step.script, "args": args}
                out = await self.scripts.run(
                    step.script, args,
                    timeout=resolve_number(step.timeout_sec, context, "timeout_sec") or None,
                )
                if out.get("exit_code") not in (0, None):
                    raise WorkflowError(
                        f"Script '{step.script}' exited {out.get('exit_code')}",
                        details={"output": str(out.get('output', ''))[-1500:]},
                    )
                return out
            case "wait":
                seconds = resolve_number(step.seconds, context, "seconds")
                if not dry_run:
                    await asyncio.sleep(seconds)
                return {"waited_sec": seconds}
            case "wait_for":
                if step.until is None:
                    raise WorkflowError("wait_for step requires an 'until' condition.")
                if dry_run:
                    return {"would_wait_for": step.until.model_dump(), "endpoint": step.endpoint}
                return await self._wait_for(step, context)
            case "sample":
                if dry_run:
                    return {"would_sample": step.endpoint, "duration_sec": step.duration_sec}
                return await self._sample(step, context)
            case "report":
                data = substitute(step.data, context) if step.data is not None else context
                if dry_run:
                    return {"would_report": step.title}
                report = self.reports.generate(
                    title=substitute(step.title, context) or "LANforge workflow report",
                    data=data,
                )
                return report
            case "log":
                message = substitute(step.message, context)
                logger.info("workflow: %s", message)
                return {"message": message}
        raise WorkflowError(f"Unknown step action '{step.action}'.")

    async def _wait_for(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        assert step.until is not None
        timeout_sec = resolve_number(step.timeout_sec, context, "timeout_sec")
        interval_sec = resolve_number(step.interval_sec, context, "interval_sec")
        deadline = time.monotonic() + timeout_sec
        polls = 0
        cond = Condition(
            field=substitute(step.until.field, context),
            op=step.until.op,
            value=substitute(step.until.value, context),
            match=step.until.match,
        )
        while True:
            q = await self.api.query(
                substitute(step.endpoint, context),
                columns=step.columns or None,
                eids=substitute(step.eids, context) or None,
            )
            polls += 1
            if check_condition(q["rows"], cond):
                return {"satisfied": True, "polls": polls, "rows": q["rows"]}
            if time.monotonic() >= deadline:
                raise WorkflowError(
                    f"wait_for timed out after {timeout_sec}s "
                    f"({cond.field} {cond.op} {cond.value}, match={cond.match}).",
                    details={"last_rows": q["rows"][:10], "polls": polls},
                )
            await asyncio.sleep(interval_sec)

    async def _sample(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        samples: list[dict[str, Any]] = []
        duration_sec = resolve_number(step.duration_sec, context, "duration_sec")
        interval_sec = resolve_number(step.interval_sec, context, "interval_sec")
        deadline = time.monotonic() + duration_sec
        while True:
            t = time.monotonic()
            q = await self.api.query(
                substitute(step.endpoint, context),
                columns=step.columns or None,
                eids=substitute(step.eids, context) or None,
            )
            samples.append({"t": _now(), "rows": q["rows"]})
            if t + interval_sec >= deadline:
                break
            await asyncio.sleep(interval_sec)
        return {"endpoint": step.endpoint, "interval_sec": interval_sec, "samples": samples}
