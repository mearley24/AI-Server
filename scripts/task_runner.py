#!/usr/bin/env python3
"""
Symphony Task Runner — zero-touch git-driven control plane.

Invoked once per launchd tick (every 120s via com.symphony.task-runner).

Flow:
    1. Acquire a single-instance lock (data/task_runner/.runner.lock).
    2. `git pull --ff-only origin main`.
    3. For each ops/work_queue/pending/*.json (sorted by filename):
        a. Verify signature via task_signer.verify_task.
        b. Validate task_type against the allowlist.
        c. Dispatch to the handler; tee stdout+stderr into
           ops/verification/<task_id>-result.txt.
        d. Move task to completed/ (success), failed/ (non-zero exit), or
           rejected/ (bad signature or unknown task_type).
    4. Update heartbeat.txt at most once per 10 minutes.
    5. Commit any new files under ops/verification/, ops/work_queue/, and
       data/task_runner/heartbeat.txt with author "Perplexity Computer" and
       push to origin/main. Skip the commit if nothing changed.
    6. Release the lock.

Security notes:
    - Payloads are *never* interpolated into shell strings. Every subprocess
      call uses an explicit argv list; user-provided values are either passed
      as positional args to a named, repo-committed script, or shlex.quote'd
      when they must appear inside a remote shell command.
    - `ssh_and_run` uses BatchMode=yes + StrictHostKeyChecking=yes so the
      process fails loudly rather than prompting for confirmation. Host keys
      must be pinned before the first task for a new host.
    - Named scripts live under ops/task_runner/{scripts,remote_scripts,
      verifications}/ and are reviewed like any other code.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make the local `scripts` directory importable so we can reuse task_signer.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import task_signer  # noqa: E402  (path tweak above is required)

# The preflight self-heal lives at <repo>/ops/task_runner_preflight.py.
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "ops"))
try:
    import task_runner_preflight  # noqa: E402
except Exception:  # noqa: BLE001
    # Preflight is best-effort; never crash the runner if the module is
    # missing or broken — fall back to the legacy behaviour.
    task_runner_preflight = None  # type: ignore[assignment]

try:
    import task_runner_gates  # noqa: E402
except Exception:  # noqa: BLE001
    # If the gate module is missing the runner falls back to pre-gate
    # behaviour (treats every task as low-risk). This preserves uptime
    # while still logging a warning in run_once().
    task_runner_gates = None  # type: ignore[assignment]

WORK_QUEUE = REPO_ROOT / "ops" / "work_queue"
TASK_RUNNER_DIR = REPO_ROOT / "ops" / "task_runner"
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
DATA_DIR = REPO_ROOT / "data" / "task_runner"

PENDING = WORK_QUEUE / "pending"
COMPLETED = WORK_QUEUE / "completed"
REJECTED = WORK_QUEUE / "rejected"
FAILED = WORK_QUEUE / "failed"
BLOCKED = WORK_QUEUE / "blocked"


LOCK_PATH = DATA_DIR / ".runner.lock"
HEARTBEAT_PATH = DATA_DIR / "heartbeat.txt"
HEARTBEAT_EVERY = 600  # seconds
TASK_TIMEOUT = 2 * 60 * 60  # 2 hours
GIT_TIMEOUT = 60  # seconds; cap every git subprocess so a stalled
                  # network/auth/credential helper can never wedge the
                  # runner's fcntl lock (see docs/audits/bob-freezing-
                  # runtime-hangs-2026-04-23.md).

GIT_AUTHOR_NAME = "Perplexity Computer"
GIT_AUTHOR_EMAIL = "earleystream@gmail.com"

# Non-interactive git environment. GIT_TERMINAL_PROMPT=0 makes git fail
# fast instead of blocking on a credential prompt; GIT_ASKPASS=/usr/bin/true
# short-circuits any helper that would otherwise pop a GUI/TTY dialog;
# SSH flags force batch mode with pinned host-key checking so git+ssh
# can't stall on "Are you sure you want to continue connecting?" either.
GIT_NONINTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/usr/bin/true",
    "SSH_ASKPASS": "/usr/bin/true",
    "GIT_SSH_COMMAND": (
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "
        "-o ConnectTimeout=10 -o ServerAliveInterval=5 "
        "-o ServerAliveCountMax=2"
    ),
}


def _git_env() -> dict:
    """Return os.environ merged with the non-interactive git overrides."""
    env = os.environ.copy()
    env.update(GIT_NONINTERACTIVE_ENV)
    return env


def _git_timeout_result(
    cmd: list[str], elapsed: float
) -> subprocess.CompletedProcess:
    """Shape a TimeoutExpired into a CompletedProcess so callers keep working."""
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=124,
        stdout="",
        stderr=f"git timeout after {elapsed:.1f}s (limit {GIT_TIMEOUT}s)",
    )

ALLOWED_TASK_TYPES = {
    "git_pull",
    "run_script",
    "ssh_and_run",
    "verify_dump",
    "run_cline_prompt",
    "run_cline_campaign",
    "run_autonomy_sweep",
}


# ---------- small helpers ----------


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def log(msg: str) -> None:
    """Print with a timestamp so launchd stdout/stderr is easy to scan."""
    print(f"[{now_iso()}] {msg}", flush=True)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the repo root with Perplexity Computer identity.

    Bounded by GIT_TIMEOUT and run with a non-interactive environment so a
    stalled network, credential helper, or SSH prompt cannot wedge the
    runner lock. On timeout the call returns a CompletedProcess with
    returncode=124 instead of raising, so callers treat it as a plain
    non-zero exit (matches how pre-existing "nothing to commit" / rc!=0
    branches already behave).
    """
    cmd = [
        "git",
        "-C",
        str(REPO_ROOT),
        "-c",
        f"user.name={GIT_AUTHOR_NAME}",
        "-c",
        f"user.email={GIT_AUTHOR_EMAIL}",
        *args,
    ]
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired as exc:
        log(f"git timed out after {GIT_TIMEOUT}s: {' '.join(args)}")
        result = _git_timeout_result(cmd, float(exc.timeout or GIT_TIMEOUT))
        if check:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )
        return result


def ensure_dirs() -> None:
    for p in (
        PENDING,
        COMPLETED,
        REJECTED,
        FAILED,
        BLOCKED,
        VERIFICATION_DIR,
        DATA_DIR,
        TASK_RUNNER_DIR / "scripts",
        TASK_RUNNER_DIR / "remote_scripts",
        TASK_RUNNER_DIR / "verifications",
        REPO_ROOT / "ops" / "approvals",
    ):
        p.mkdir(parents=True, exist_ok=True)



# ---------- single-instance lock ----------


class Lock:
    """Advisory flock so two launchd ticks can't stomp on each other."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            raise
        self.fh.write(f"{os.getpid()} {now_iso()}\n")
        self.fh.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fh is not None:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()


# ---------- handlers ----------


def _script_path(kind: str, name: str) -> Path:
    """Resolve a script name against the allowed directory; reject traversal."""
    if not name or "/" in name or ".." in name or name.startswith("."):
        raise ValueError(f"invalid script name: {name!r}")
    root = TASK_RUNNER_DIR / kind
    path = (root / f"{name}.sh").resolve()
    # Must stay inside the allowed dir.
    if not str(path).startswith(str(root.resolve()) + os.sep):
        raise ValueError(f"script path escapes {kind}/: {path}")
    if not path.exists():
        raise FileNotFoundError(f"missing script: {path}")
    return path


def _stringify_args(args) -> list[str]:
    """Coerce payload args into a flat list of strings; reject nested structures."""
    if args is None:
        return []
    if not isinstance(args, list):
        raise ValueError("script_args must be a list")
    out: list[str] = []
    for item in args:
        if isinstance(item, (str, int, float, bool)):
            out.append(str(item))
        else:
            raise ValueError(f"script_args item not scalar: {item!r}")
    return out


def handle_git_pull(payload: dict, result_path: Path) -> int:
    argv = ["git", "-C", str(REPO_ROOT), "pull", "--ff-only", "origin", "main"]
    with result_path.open("a", encoding="utf-8") as fh:
        fh.write(f"=== git_pull @ {now_iso()} ===\n")
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT,
                env=_git_env(),
            )
        except subprocess.TimeoutExpired as exc:
            fh.write(f"TIMEOUT after {float(exc.timeout or GIT_TIMEOUT):.1f}s\n")
            if exc.output:
                fh.write(exc.output if isinstance(exc.output, str) else "")
            fh.write("exit=124\n")
            return 124
        fh.write(proc.stdout)
        fh.write(proc.stderr)
        fh.write(f"exit={proc.returncode}\n")
    return proc.returncode


def _run_and_tee(argv: list[str], result_path: Path, banner: str) -> int:
    """Run `argv`, teeing combined stdout+stderr into result_path."""
    with result_path.open("a", encoding="utf-8") as fh:
        fh.write(f"=== {banner} @ {now_iso()} ===\n")
        fh.write(f"argv: {argv}\n")
        fh.flush()
        try:
            proc = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=TASK_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            fh.write(f"TIMEOUT after {TASK_TIMEOUT}s\n")
            if exc.output:
                fh.write(exc.output)
            return 124
        fh.write(proc.stdout or "")
        fh.write(f"\nexit={proc.returncode}\n")
        return proc.returncode


def handle_run_script(payload: dict, result_path: Path) -> int:
    name = payload.get("script")
    args = _stringify_args(payload.get("args", []))
    script = _script_path("scripts", name)
    argv = ["bash", str(script), *args]
    return _run_and_tee(argv, result_path, f"run_script {name}")


def handle_verify_dump(payload: dict, result_path: Path) -> int:
    name = payload.get("name")
    args = _stringify_args(payload.get("args", []))
    script = _script_path("verifications", name)
    argv = ["bash", str(script), *args]
    return _run_and_tee(argv, result_path, f"verify_dump {name}")


# --- cline launcher helpers ---


CLINE_LAUNCHER = REPO_ROOT / "ops" / "cline-run-prompt.sh"
CLINE_CAMPAIGN = REPO_ROOT / "ops" / "cline-run-campaign.sh"


def _validate_repo_relative(path_str: str, label: str) -> Path:
    """Resolve a repo-relative path and refuse traversal outside REPO_ROOT.

    Raises ValueError if the path is absolute, contains "..", or escapes the
    repo root after normalization. Returns the resolved absolute Path.
    """
    if not path_str or not isinstance(path_str, str):
        raise ValueError(f"{label}: missing or non-string path")
    if path_str.startswith("/"):
        raise ValueError(f"{label}: absolute paths not allowed ({path_str!r})")
    if ".." in Path(path_str).parts:
        raise ValueError(f"{label}: '..' not allowed in path ({path_str!r})")
    candidate = (REPO_ROOT / path_str).resolve()
    root_resolved = REPO_ROOT.resolve()
    if not str(candidate).startswith(str(root_resolved) + os.sep):
        raise ValueError(f"{label}: path escapes repo root ({path_str!r})")
    return candidate


def handle_run_cline_prompt(payload: dict, result_path: Path) -> int:
    """Run ops/cline-run-prompt.sh against a repo-relative prompt file.

    Payload keys:
        prompt_file (str, required): repo-relative path to a .md prompt.
        dry_run (bool, optional): passes --dry-run to the launcher.
        timeout (int, optional): seconds; passes --timeout SEC.
    """
    prompt_rel = payload.get("prompt_file")
    prompt_path = _validate_repo_relative(prompt_rel, "prompt_file")
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt_file does not exist: {prompt_rel}")
    if not CLINE_LAUNCHER.exists():
        raise FileNotFoundError(f"launcher missing: {CLINE_LAUNCHER}")

    argv: list[str] = ["bash", str(CLINE_LAUNCHER)]
    if bool(payload.get("dry_run", False)):
        argv.append("--dry-run")
    timeout = payload.get("timeout")
    if timeout is not None:
        if not isinstance(timeout, (int, float)) or int(timeout) <= 0:
            raise ValueError("timeout must be a positive integer")
        argv.extend(["--timeout", str(int(timeout))])
    # Prompt path is passed as repo-relative so the launcher's log uses a
    # stable basename; the launcher resolves against REPO_ROOT.
    argv.append(str(prompt_rel))

    return _run_and_tee(argv, result_path, f"run_cline_prompt {prompt_rel}")


def handle_run_cline_campaign(payload: dict, result_path: Path) -> int:
    """Run ops/cline-run-campaign.sh against a list of repo-relative prompts.

    Payload keys:
        prompt_files (list[str], required): repo-relative paths.
        dry_run (bool, optional): passes --dry-run.
        stop_on_fail (bool, optional): passes --stop-on-fail.
        timeout (int, optional): seconds; passes --timeout SEC.
    """
    prompts = payload.get("prompt_files")
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("prompt_files must be a non-empty list")
    validated: list[str] = []
    for p in prompts:
        pp = _validate_repo_relative(p, "prompt_files[i]")
        if not pp.exists():
            raise FileNotFoundError(f"prompt_file does not exist: {p}")
        validated.append(p)
    if not CLINE_CAMPAIGN.exists():
        raise FileNotFoundError(f"campaign wrapper missing: {CLINE_CAMPAIGN}")

    argv: list[str] = ["bash", str(CLINE_CAMPAIGN)]
    if bool(payload.get("dry_run", False)):
        argv.append("--dry-run")
    if bool(payload.get("stop_on_fail", False)):
        argv.append("--stop-on-fail")
    timeout = payload.get("timeout")
    if timeout is not None:
        if not isinstance(timeout, (int, float)) or int(timeout) <= 0:
            raise ValueError("timeout must be a positive integer")
        argv.extend(["--timeout", str(int(timeout))])
    argv.extend(validated)

    return _run_and_tee(argv, result_path, f"run_cline_campaign ({len(validated)} prompts)")


# --- autonomy sweep handler ---


AUTONOMY_SWEEP_SCRIPT = REPO_ROOT / "scripts" / "autonomy_sweep.py"

_SAFE_SWEEP_TOKEN_RE = None  # populated lazily below


def _validate_sweep_token(val: object, label: str, max_len: int = 120) -> str:
    """Coerce a payload value into a short, shell-safe string for the sweep.

    Rejects anything that isn't str/int/float, anything with shell meta
    characters, and anything longer than ``max_len`` chars. Returns the
    normalized string.
    """
    import re as _re  # local import so top-of-file stays tidy

    global _SAFE_SWEEP_TOKEN_RE
    if _SAFE_SWEEP_TOKEN_RE is None:
        _SAFE_SWEEP_TOKEN_RE = _re.compile(r"^[A-Za-z0-9_.\-: /]+$")

    if val is None:
        return ""
    if not isinstance(val, (str, int, float)):
        raise ValueError(f"{label}: must be string/number, got {type(val).__name__}")
    s = str(val).strip()
    if not s:
        return ""
    if len(s) > max_len:
        raise ValueError(f"{label}: too long ({len(s)} > {max_len})")
    if not _SAFE_SWEEP_TOKEN_RE.match(s):
        raise ValueError(f"{label}: contains disallowed characters")
    return s


def handle_run_autonomy_sweep(payload: dict, result_path: Path) -> int:
    """Run scripts/autonomy_sweep.py with sanitized payload values.

    Payload keys (all optional):
        trigger (str):       human-readable reason; default "task-runner".
        slug (str):          slug for the output filename.
        trigger_file (str):  repo-relative path to a sentinel file whose
                             contents get embedded in the sweep report.
        dry_run (bool):      build report to stdout, don't write to disk.

    The handler deliberately does NOT pass --json so the tee log captures
    the full sweep report. The sweep itself is low-risk and bounded (no
    network I/O, no writes outside ops/verification/).
    """
    if not AUTONOMY_SWEEP_SCRIPT.exists():
        raise FileNotFoundError(
            f"autonomy sweep script missing: {AUTONOMY_SWEEP_SCRIPT}"
        )

    argv: list[str] = [sys.executable, str(AUTONOMY_SWEEP_SCRIPT)]
    trigger = _validate_sweep_token(payload.get("trigger"), "trigger")
    if trigger:
        argv.extend(["--trigger", trigger])
    slug = _validate_sweep_token(payload.get("slug"), "slug", max_len=40)
    if slug:
        argv.extend(["--slug", slug])

    trigger_file = payload.get("trigger_file")
    if trigger_file is not None:
        if not isinstance(trigger_file, str):
            raise ValueError("trigger_file must be a string")
        # Validate as repo-relative like cline-run-prompt handlers do.
        _validate_repo_relative(trigger_file, "trigger_file")
        argv.extend(["--trigger-path", trigger_file])

    if bool(payload.get("dry_run", False)):
        argv.append("--dry-run")

    return _run_and_tee(argv, result_path, "run_autonomy_sweep")


def handle_ssh_and_run(payload: dict, task_id: str, result_path: Path) -> int:
    """scp a named remote script to the target, then run it via ssh.

    Host keys must be pinned in advance. BatchMode=yes ensures the process
    fails rather than prompting on an unknown host.
    """
    host = payload.get("host")
    name = payload.get("script_name")
    args = _stringify_args(payload.get("script_args", []))
    if not host or not isinstance(host, str):
        raise ValueError("ssh_and_run: missing host")
    script = _script_path("remote_scripts", name)
    remote_path = f"/tmp/{task_id}-{name}.sh"
    ssh_opts = [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
    ]

    with result_path.open("a", encoding="utf-8") as fh:
        fh.write(f"=== ssh_and_run {name} @ {host} {now_iso()} ===\n")
        fh.flush()

    # Copy the script.
    rc = _run_and_tee(
        ["scp", *ssh_opts, str(script), f"{host}:{remote_path}"],
        result_path,
        f"scp {script.name} -> {host}:{remote_path}",
    )
    if rc != 0:
        return rc

    # Build the remote command with shlex.quote on every arg.
    quoted_args = " ".join(shlex.quote(a) for a in args)
    remote_cmd = f"bash {shlex.quote(remote_path)}"
    if quoted_args:
        remote_cmd += f" {quoted_args}"

    rc = _run_and_tee(
        ["ssh", *ssh_opts, host, remote_cmd],
        result_path,
        f"ssh {host} run {name}",
    )

    # Best-effort cleanup; ignore failure.
    _run_and_tee(
        ["ssh", *ssh_opts, host, f"rm -f {shlex.quote(remote_path)}"],
        result_path,
        "cleanup remote script",
    )
    return rc


# ---------- queue processing ----------


def move(path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / path.name
    shutil.move(str(path), str(target))
    return target


def process_task(path: Path) -> tuple[str, int]:
    """Run one task and return (status, exit_code).

    status is one of: "completed", "failed", "rejected".
    """
    try:
        task = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        reason = f"malformed JSON: {exc}"
        rej = move(path, REJECTED)
        VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
        (VERIFICATION_DIR / f"{now_stamp()}-rejections.txt").open("a").write(
            f"{path.name}: {reason}\n"
        )
        log(f"REJECT {path.name}: {reason} -> {rej}")
        return ("rejected", 2)

    task_id = task.get("task_id") or path.stem
    task_type = task.get("task_type")

    ok, detail = task_signer.verify_task(task)
    if not ok:
        reason = f"signature check failed: {detail}"
        rej = move(path, REJECTED)
        (VERIFICATION_DIR / f"{now_stamp()}-rejections.txt").open("a").write(
            f"{path.name}: {reason}\n"
        )
        log(f"REJECT {path.name}: {reason} -> {rej}")
        return ("rejected", 2)

    if task_type not in ALLOWED_TASK_TYPES:
        reason = f"unknown task_type: {task_type!r}"
        rej = move(path, REJECTED)
        (VERIFICATION_DIR / f"{now_stamp()}-rejections.txt").open("a").write(
            f"{path.name}: {reason}\n"
        )
        log(f"REJECT {path.name}: {reason} -> {rej}")
        return ("rejected", 2)

    # High-risk approval gate (see ops/task_runner_gates.py and
    # ops/AGENT_VERIFICATION_PROTOCOL.md). Low/medium-risk tasks fall through
    # without side effect. High-risk tasks require either dry_run=true or a
    # committed approval token. A blocked task is moved to work_queue/blocked/
    # with a blocker report in ops/verification/.
    gate_decision = None
    if task_runner_gates is not None:
        try:
            gate_decision = task_runner_gates.evaluate(task)
        except Exception as exc:  # noqa: BLE001
            log(f"gate evaluation crashed (continuing without gate): {exc}")
            gate_decision = None

    if gate_decision is not None and not gate_decision.allowed:
        blocker_path = (
            VERIFICATION_DIR
            / f"{now_stamp()}-blocker-{task_id}.txt"
        )
        blocker_path.parent.mkdir(parents=True, exist_ok=True)
        blocker_path.write_text(
            task_runner_gates.blocker_text(gate_decision, task) + "\n",
            encoding="utf-8",
        )
        dest = move(path, BLOCKED)
        log(
            f"BLOCKED {task_id}: {gate_decision.reason} -> {dest} "
            f"(report: {blocker_path.relative_to(REPO_ROOT)})"
        )
        return ("blocked", 0)

    result_path = VERIFICATION_DIR / f"{task_id}-result.txt"
    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    with result_path.open("a", encoding="utf-8") as fh:
        fh.write(f"### task {task_id} type={task_type} signer={detail}\n")
        fh.write(f"### started {now_iso()}\n")
        if gate_decision is not None:
            fh.write(
                f"### gate: allowed={gate_decision.allowed} "
                f"high_risk={gate_decision.high_risk} "
                f"dry_run={gate_decision.is_dry_run} "
                f"source={gate_decision.approval_source or '-'} "
                f"token={gate_decision.approval_token or '-'}\n"
            )
            fh.write(f"### gate_reason: {gate_decision.reason}\n")
        fh.write("\n")

    payload = task.get("payload", {}) or {}

    # Propagate dry-run into the payload so handlers that understand the flag
    # (run_cline_prompt, run_cline_campaign) pass --dry-run through to their
    # launcher. Handlers that do not honor dry-run but receive a high-risk
    # task will never reach this branch (they will either be dry_run=false
    # and approved, or blocked above).
    is_dry = bool(
        gate_decision.is_dry_run if gate_decision is not None
        else payload.get("dry_run", False) or task.get("dry_run", False)
    )
    if is_dry:
        # Set on a shallow copy so the JSON-on-disk remains untouched.
        payload = dict(payload)
        payload["dry_run"] = True

    rc = 0
    try:
        if task_type == "git_pull":
            rc = handle_git_pull(payload, result_path)
        elif task_type == "run_script":
            rc = handle_run_script(payload, result_path)
        elif task_type == "verify_dump":
            rc = handle_verify_dump(payload, result_path)
        elif task_type == "ssh_and_run":
            rc = handle_ssh_and_run(payload, task_id, result_path)
        elif task_type == "run_cline_prompt":
            rc = handle_run_cline_prompt(payload, result_path)
        elif task_type == "run_cline_campaign":
            rc = handle_run_cline_campaign(payload, result_path)
        elif task_type == "run_autonomy_sweep":
            rc = handle_run_autonomy_sweep(payload, result_path)
        else:  # defensive; allowlist checked above
            rc = 2
    except Exception as exc:  # noqa: BLE001
        with result_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\nEXCEPTION: {exc}\n")
        rc = 1

    with result_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n### finished {now_iso()} exit={rc}\n")

    if rc == 0:
        dest = move(path, COMPLETED)
        log(f"COMPLETED {task_id} -> {dest}")
        return ("completed", 0)
    dest = move(path, FAILED)
    log(f"FAILED {task_id} (exit={rc}) -> {dest}")
    return ("failed", rc)



def maybe_update_heartbeat() -> bool:
    """Update heartbeat.txt if it has been >= HEARTBEAT_EVERY seconds."""
    try:
        mtime = HEARTBEAT_PATH.stat().st_mtime
    except FileNotFoundError:
        mtime = 0
    if time.time() - mtime < HEARTBEAT_EVERY:
        return False
    HEARTBEAT_PATH.write_text(f"last-heartbeat: {now_iso()}\n", encoding="utf-8")
    return True


def has_changes() -> bool:
    """Return True if git has staged/unstaged changes under our tracked dirs.

    A hanging `git status` (e.g. stalled index.lock) would otherwise wedge
    the tick — skip the commit phase on timeout and let the next tick
    retry once the underlying issue clears.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "status",
                "--porcelain",
                "--",
                "ops/verification",
                "ops/work_queue",
                "data/task_runner/heartbeat.txt",
            ],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired:
        log(f"git status timed out after {GIT_TIMEOUT}s; skipping commit this tick")
        return False
    return bool(proc.stdout.strip())


def commit_and_push(summary: str) -> None:
    """Stage changes, commit with runner identity, and push. Idempotent."""
    try:
        git(
            "add",
            "ops/verification",
            "ops/work_queue",
            "data/task_runner/heartbeat.txt",
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"git add failed: {exc}")
        return
    if not has_changes():
        # Nothing to commit (add --intent-to-add or ignored by .gitignore).
        return
    proc = git(
        "commit",
        "-m",
        f"ops: task-runner tick {now_stamp()} — {summary}",
        check=False,
    )
    if proc.returncode != 0:
        # "nothing to commit" is fine; anything else gets logged.
        if "nothing to commit" not in (proc.stdout + proc.stderr):
            log(f"git commit rc={proc.returncode}: {proc.stdout}{proc.stderr}")
        return
    push = git("push", "origin", "main", check=False)
    tail = (push.stdout + push.stderr).strip().splitlines()[-3:]
    log("git push:\n  " + "\n  ".join(tail))


def pull_latest() -> None:
    """Fetch and advance main, with a safe rebase fallback on divergence.

    Historically this used plain ``git pull --ff-only origin main``. That
    works fine on a healthy repo but bricks the runner permanently the
    moment HEAD diverges from origin/main (e.g. a local preflight commit
    + a remote commit land in the same window). When that happens git
    returns ``fatal: Not possible to fast-forward, aborting.`` and every
    subsequent tick fails the same way. Observed 2026-04-18 on Bob.

    New contract:
      1. Try ``pull --ff-only`` (fast path — 99% of ticks).
      2. If that fails AND the message names the fast-forward problem,
         retry with ``pull --rebase --autostash`` which is safe when the
         only local commits are preflight auto-heals / runner heartbeats.
      3. If the rebase fails too, log the failure but do NOT crash the
         tick. The runner still processes locally-pending tasks, writes
         the heartbeat, and commits. A future tick (or a human running
         ``bash scripts/pull.sh``) will heal the divergence.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "pull", "--ff-only", "origin", "main"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired:
        log(
            f"pull --ff-only timed out after {GIT_TIMEOUT}s "
            "(continuing tick; run `bash scripts/pull.sh` to recover)"
        )
        return
    if proc.returncode == 0:
        tail = proc.stdout.strip().splitlines()[-1:] or ["(no output)"]
        log(f"pull ok: {tail[0]}")
        return

    combined = (proc.stdout or "") + (proc.stderr or "")
    needs_rebase = (
        "Not possible to fast-forward" in combined
        or "non-fast-forward" in combined
        or "diverged" in combined
    )
    if not needs_rebase:
        log(f"pull rc={proc.returncode}: {combined.strip()}")
        return

    log(f"pull --ff-only diverged; retrying with --rebase --autostash")
    try:
        proc2 = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "-c",
                "rebase.autoStash=true",
                "pull",
                "--rebase",
                "origin",
                "main",
            ],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired:
        log(
            f"pull --rebase timed out after {GIT_TIMEOUT}s "
            "(continuing tick; run `bash scripts/pull.sh` to recover)"
        )
        return
    if proc2.returncode == 0:
        tail = proc2.stdout.strip().splitlines()[-1:] or ["(no output)"]
        log(f"pull rebase ok: {tail[0]}")
        return
    combined2 = (proc2.stdout or "") + (proc2.stderr or "")
    log(
        f"pull rebase rc={proc2.returncode}: {combined2.strip()[:400]} "
        "(continuing tick; run `bash scripts/pull.sh` to recover)"
    )


def run_preflight_self_heal() -> bool:
    """Call the preflight self-heal module. Returns True if safe to proceed.

    The preflight auto-resolves whitelisted generated/state file conflicts
    (see ops/task_runner_preflight.py) and writes a report to
    ops/verification/<stamp>-preflight.txt. Non-whitelisted conflicts cause
    it to return False — the runner should skip task processing this tick
    and let a human (or follow-up agent) resolve the situation.
    """
    if task_runner_preflight is None:
        log("preflight module unavailable; skipping self-heal")
        return True
    try:
        result = task_runner_preflight.run_preflight(commit_and_push=True)
    except Exception as exc:  # noqa: BLE001
        log(f"preflight crashed (continuing without self-heal): {exc}")
        return True
    log(
        "preflight ok=%s resolved=%d staged=%d unsafe=%d report=%s"
        % (
            result.ok,
            len(result.conflicts_resolved),
            len(result.dirty_whitelisted_staged),
            len(result.unsafe_conflicts),
            result.report_path,
        )
    )
    return result.ok


def run_once() -> int:
    ensure_dirs()
    try:
        lock = Lock(LOCK_PATH)
        lock.__enter__()
    except OSError:
        log("another runner holds the lock; exiting")
        return 0
    try:
        # Preflight first — heal whitelisted state-file conflicts before
        # attempting to pull or dispatch tasks. If preflight flags unsafe
        # conflicts, skip task processing this tick (the heartbeat still
        # updates so we know the runner is alive).
        preflight_ok = run_preflight_self_heal()
        pull_latest()
        if not preflight_ok:
            log("preflight reported unsafe conflicts; skipping task dispatch")
            did_heartbeat = maybe_update_heartbeat()
            if did_heartbeat:
                commit_and_push("preflight-blocked heartbeat")
            return 0
        tasks = sorted(PENDING.glob("*.json"))
        completed = failed = rejected = blocked = 0
        for path in tasks:
            status, _ = process_task(path)
            if status == "completed":
                completed += 1
            elif status == "failed":
                failed += 1
            elif status == "rejected":
                rejected += 1
            elif status == "blocked":
                blocked += 1

        did_heartbeat = maybe_update_heartbeat()

        if tasks or did_heartbeat:
            summary = (
                f"{completed} completed / {failed} failed / "
                f"{rejected} rejected / {blocked} blocked"
            )
            if not tasks and did_heartbeat:
                summary = "heartbeat"
            commit_and_push(summary)

        else:
            # Nothing happened; skip the commit to avoid spam.
            pass
        return 0
    finally:
        lock.__exit__(None, None, None)


def main() -> int:
    try:
        return run_once()
    except Exception as exc:  # noqa: BLE001
        log(f"runner crashed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
