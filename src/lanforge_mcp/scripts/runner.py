"""Run lanforge-scripts py-scripts locally (subprocess) or remotely (SSH).

Supports foreground runs with a timeout and background runs with status /
output-tail / cancel. ``--mgr`` is injected automatically when the script
accepts it and the caller didn't supply one, so the LLM never has to remember
the LANforge address.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shlex
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..connection.ssh_client import LFSshClient
from ..errors import ScriptError, TimeoutError_
from ..models import ScriptRunInfo, ScriptsConfig
from ..safety import SafetyGuard
from .discovery import ScriptInfo, ScriptRegistry

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 200_000
TAIL_CHARS = 4000


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _Run:
    def __init__(self, info: ScriptRunInfo):
        self.info = info
        self.output: list[str] = []
        self.output_len = 0
        self.task: asyncio.Task | None = None
        self.process: asyncio.subprocess.Process | None = None

    def append(self, chunk: str) -> None:
        if self.output_len < MAX_OUTPUT_CHARS:
            self.output.append(chunk)
            self.output_len += len(chunk)

    def text(self) -> str:
        return "".join(self.output)


class ScriptRunner:
    def __init__(
        self,
        registry: ScriptRegistry,
        config: ScriptsConfig,
        safety: SafetyGuard,
        ssh: LFSshClient | None = None,
        mgr_host: str = "localhost",
        system_id: str = "",
    ):
        self.registry = registry
        self.config = config
        self.safety = safety
        self.ssh = ssh
        self.mgr_host = mgr_host
        self.system_id = system_id
        self._runs: dict[str, _Run] = {}

    # ------------------------------------------------------------ argument prep

    async def build_argv(self, name: str, args: dict[str, Any]) -> tuple[ScriptInfo, list[str]]:
        info = await self.registry.load_schema(name)
        schema = info.schema or {"properties": {}}
        props: dict[str, Any] = schema.get("properties", {})
        argv: list[str] = []
        for key, value in args.items():
            prop = props.get(key)
            flag = prop["flag"] if prop else f"--{key}"
            if prop and prop.get("is_flag"):
                if value in (True, "true", "True", 1, "1"):
                    argv.append(flag)
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    argv.extend([flag, str(item)])
            else:
                argv.extend([flag, str(value)])
        # Auto-inject the manager address if the script supports it.
        if "mgr" in props and "mgr" not in args:
            argv.extend([props["mgr"].get("flag", "--mgr"), self.mgr_host])
        return info, argv

    # ------------------------------------------------------------------ running

    async def run(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        background: bool = False,
    ) -> dict[str, Any]:
        args = args or {}
        info, argv = await self.build_argv(name, args)
        dry = self.safety.check_script(info.name, argv, system=self.system_id)
        if dry:
            return {
                "dry_run": True,
                "script": info.name,
                "location": info.location,
                "would_run": [info.path, *argv],
            }
        timeout = timeout or self.config.default_timeout_sec

        run = _Run(
            ScriptRunInfo(
                run_id=uuid.uuid4().hex[:12],
                script=info.name,
                args=argv,
                mode="local" if info.location == "local" else "remote",
                state="running",
                started_at=_now(),
            )
        )
        self._runs[run.info.run_id] = run

        coro = self._run_local(run, info, argv) if info.location == "local" else self._run_remote(
            run, info, argv, timeout
        )
        if background:
            run.task = asyncio.ensure_future(self._guard(run, coro, timeout))
            return {"run_id": run.info.run_id, "state": "running", "background": True}

        await self._guard(run, coro, timeout)
        return self.result(run.info.run_id, tail_only=False)

    async def _guard(self, run: _Run, coro, timeout: float) -> None:
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            run.info.state = "failed"
            run.append(f"\n[lanforge-mcp] script timed out after {timeout}s and was terminated\n")
            if run.process is not None and run.process.returncode is None:
                run.process.kill()
        except asyncio.CancelledError:
            run.info.state = "cancelled"
            if run.process is not None and run.process.returncode is None:
                run.process.kill()
            raise
        except ScriptError as exc:
            run.info.state = "failed"
            run.append(f"\n[lanforge-mcp] {exc.message}\n")
        finally:
            if run.info.finished_at is None:
                run.info.finished_at = _now()
            if run.info.state == "running":
                run.info.state = "finished" if (run.info.exit_code or 0) == 0 else "failed"
            run.info.output_tail = run.text()[-TAIL_CHARS:]

    async def _run_local(self, run: _Run, info: ScriptInfo, argv: list[str]) -> None:
        script_path = Path(info.path)
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.python_exec,
                str(script_path),
                *argv,
                cwd=str(script_path.parent),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise ScriptError(
                f"Could not start '{self.config.python_exec}': {exc}",
                hint="Set scripts.python_exec to a Python interpreter that has the "
                "lanforge-scripts dependencies installed.",
            ) from exc
        run.process = process
        assert process.stdout is not None
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                break
            run.append(chunk.decode("utf-8", errors="replace"))
        run.info.exit_code = await process.wait()

    async def _run_remote(self, run: _Run, info: ScriptInfo, argv: list[str], timeout: float) -> None:
        if self.ssh is None:
            raise ScriptError("Remote script execution requires an SSH connection.")
        quoted = " ".join(shlex.quote(a) for a in argv)
        remote_dir = info.path.rsplit("/", 1)[0]
        command = f"cd {shlex.quote(remote_dir)} && {self.config.python_exec} {shlex.quote(info.path)} {quoted}"
        try:
            result = await self.ssh.exec(command, timeout=timeout)
        except TimeoutError_ as exc:
            raise ScriptError(exc.message) from exc
        run.append(result.stdout)
        if result.stderr:
            run.append("\n--- stderr ---\n" + result.stderr)
        run.info.exit_code = result.exit_code

    # ------------------------------------------------------------------ control

    def _get_run(self, run_id: str) -> _Run:
        if run_id not in self._runs:
            raise ScriptError(f"Unknown script run_id '{run_id}'.")
        return self._runs[run_id]

    def status(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        info = run.info.model_copy()
        info.output_tail = run.text()[-TAIL_CHARS:]
        return info.model_dump()

    def result(self, run_id: str, tail_only: bool = True, max_chars: int = 20000) -> dict[str, Any]:
        run = self._get_run(run_id)
        text = run.text()
        return {
            **run.info.model_dump(exclude={"output_tail"}),
            "output": text[-max_chars:] if tail_only else text[:max_chars],
            "output_truncated": len(text) > max_chars,
        }

    async def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        if run.task is not None and not run.task.done():
            run.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run.task
        elif run.process is not None and run.process.returncode is None:
            run.process.kill()
            run.info.state = "cancelled"
        return {"run_id": run_id, "state": run.info.state}

    def list_runs(self) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in r.info.model_dump().items() if k != "output_tail"}
            for r in self._runs.values()
        ]
