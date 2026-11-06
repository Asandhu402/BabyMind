"""OS-level sandbox for running project commands.

Linux backend: user + mount + PID + network namespaces via ``unshare``, a
tmpfs root, read-only system bind mounts, a minimal ``/dev``, a private
``/tmp``, and only the project directory mounted writable. That is real
kernel-enforced isolation: no network, no access to the host home directory
(outside the project), no writes to system paths, and children die with the
parent.

``self_test()`` actually runs the probes and returns the evidence, so
``verified`` is only true when the boundary was demonstrated on this machine.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

LAUNCHER_SOURCE = r'''
"""Enter the prepared namespaces, build a minimal root, and exec the command."""
import json
import os
import socket
import subprocess
import sys
import fcntl

spec = json.loads(os.environ["BABYMIND_SANDBOX_SPEC"])
newroot = spec["newroot"]
os.makedirs(newroot, exist_ok=True)


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def bind(src, dst, read_only):
    target = newroot + dst
    if not os.path.exists(src):
        return
    if os.path.isdir(src):
        os.makedirs(target, exist_ok=True)
        run("mount", "--rbind", src, target)
    else:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.exists(target):
            open(target, "a").close()
        run("mount", "--bind", src, target)
    if read_only:
        run("mount", "-o", "remount,bind,ro", target)


def loopback_up():
    """Bring lo up so local-only test servers can bind 127.0.0.1."""
    try:
        descriptor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        flags = struct.unpack("16sH", fcntl.ioctl(
            descriptor.fileno(), 0x8913, struct.pack("16sH", b"lo", 0)))[1]
        fcntl.ioctl(descriptor.fileno(), 0x8914,
                    struct.pack("16sH", b"lo", flags | 0x1))
        descriptor.close()
    except Exception:
        pass


import struct

run("mount", "-t", "tmpfs", "tmpfs", newroot)
for path in ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc"):
    bind(path, path, True)
for path in spec.get("readonly_binds", []):
    bind(path, path, True)

os.makedirs(newroot + "/dev", exist_ok=True)
run("mount", "-t", "tmpfs", "tmpfs", newroot + "/dev")
for name, major, minor in (("null", 1, 3), ("zero", 1, 5), ("random", 1, 8), ("urandom", 1, 9)):
    node = newroot + "/dev/" + name
    try:
        os.mknod(node, 0o020666, os.makedev(major, minor))
    except OSError:
        bind("/dev/" + name, "/dev/" + name, False)

os.makedirs(newroot + "/tmp", exist_ok=True)
run("mount", "-t", "tmpfs", "tmpfs", newroot + "/tmp")
# Re-expose interpreter prefixes beneath /tmp after mounting the private tmpfs.
# They are not part of the writable project and must remain read-only.
for path in spec.get("temp_readonly_binds", []):
    bind(path, path, True)

os.makedirs(newroot + "/proc", exist_ok=True)
run("mount", "-t", "proc", "proc", newroot + "/proc")
bind(spec["root"], spec["root"], False)

loopback_up()

os.chroot(newroot)
os.chdir(spec["cwd"])

import resource
failed_limits = []
for name, limit, value in (
    ("CPU", resource.RLIMIT_CPU, spec["cpu_seconds"]),
    ("FSIZE", resource.RLIMIT_FSIZE, spec["fsize_bytes"]),
    ("NOFILE", resource.RLIMIT_NOFILE, 512),
    ("AS", resource.RLIMIT_AS, spec["mem_bytes"]),
    ("DATA", resource.RLIMIT_DATA, spec["mem_bytes"]),
    ("NPROC", resource.RLIMIT_NPROC, spec["nproc"]),
):
    try:
        # A user namespace cannot raise a hard limit above the inherited one;
        # clamp to the hard max so the soft cap is still enforced.
        hard = resource.getrlimit(limit)[1]
        soft = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(limit, (soft, hard))
    except (ValueError, OSError) as error:
        failed_limits.append(name + ":" + str(error))
if failed_limits:
    # Surface enforcement failures instead of silently continuing.
    sys.stderr.write("LIMIT_FAILED " + ",".join(failed_limits) + "\n")
    sys.stderr.flush()

# The chroot intentionally has no host /sys mount. Do not pretend that
# an in-chroot cgroup write enforces physical RSS: the RLIMIT_AS/RLIMIT_DATA
# caps below constrain address space/data segments, not total physical RAM.
sys.stderr.write("CGROUP_MEM_UNAVAILABLE not-delegated-before-chroot\\n")
sys.stderr.flush()

os.execvpe(spec["argv"][0], spec["argv"], spec["env"])
'''

DEFAULT_CPU_SECONDS = 300
DEFAULT_FSIZE_BYTES = 128 * 1024 * 1024
# Address-space cap so a sandboxed process cannot exhaust host memory.
DEFAULT_MEM_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_NPROC = 256


def _mem_bytes() -> int:
    raw = os.getenv("BABYMIND_SANDBOX_MEM_BYTES", "").strip()
    if not raw:
        return DEFAULT_MEM_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MEM_BYTES
    return max(64 * 1024 * 1024, min(value, 64 * 1024 * 1024 * 1024))


class SandboxUnavailable(RuntimeError):
    """Raised when a sandbox was required but no backend can provide one."""


@dataclass(frozen=True)
class Backend:
    name: str
    available: bool
    detail: str


def _linux_backend() -> Backend:
    if sys.platform != "linux":
        return Backend("none", False, "Only the Linux namespace backend is implemented.")
    unshare = shutil.which("unshare")
    if unshare is None:
        return Backend("none", False, "unshare(1) was not found.")
    try:
        probe = subprocess.run(
            [unshare, "--user", "--map-root-user", "--mount", "--pid", "--net", "--fork", "true"],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Backend("none", False, f"unshare probe failed: {error}")
    if probe.returncode != 0:
        reason = (probe.stderr or b"").decode("utf-8", "replace").strip()[:200]
        return Backend("none", False, f"User namespaces are not permitted here: {reason}")
    return Backend("linux-namespaces", True, "unshare user/mount/pid/net namespaces with a chroot root.")


def backend() -> Backend:
    if getattr(sys, "frozen", False):
        from . import packaged_dev
        try:
            packaged_dev.python_path()
        except packaged_dev.PackagedDevelopmentError as error:
            return Backend("none", False, str(error))
    if not sys.platform.startswith("linux"):
        return Backend("none", False, "Only Linux namespaces are supported.")
    return _linux_backend()


def available() -> bool:
    return backend().available


def nested_sandbox_detected() -> bool:
    """True when BabyMind itself appears to run inside a container/VM sandbox.

    Namespaces created inside an existing sandbox are weaker (no cgroup or
    device isolation from the outer boundary); this only detects and reports
    the nesting, it does not remove it.
    """
    if os.path.exists("/.dockerenv"):
        return True
    if os.environ.get("container"):
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "lxc"))


def _interpreter_binds() -> tuple[list[str], list[str]]:
    """Bind the running interpreter so venvs outside /usr still work inside."""
    readonly, readonly_tmp = [], []
    if getattr(sys, "frozen", False):
        from . import packaged_dev
        prefixes = [str(packaged_dev.python_path().parents[1])]
    else:
        prefixes = [sys.prefix, sys.base_prefix]
    for prefix in dict.fromkeys(prefixes):
        if not prefix or prefix in {"/", "/usr", "/usr/local"}:
            continue
        if prefix.startswith(("/usr/", "/lib/", "/lib64/")):
            readonly.append(prefix)
        elif prefix.startswith("/tmp/"):
            readonly_tmp.append(prefix)
        else:
            readonly.append(prefix)
    return readonly, readonly_tmp


def _spec(root: Path, cwd: Path, argv: list[str], env: dict[str, str],
          allow_network: bool) -> dict:
    readonly, readonly_tmp = _interpreter_binds()
    newroot = tempfile.mkdtemp(prefix=".babymind-sandbox-")
    return {
        "root": str(root),
        "cwd": str(cwd),
        "argv": argv,
        "env": env,
        "newroot": newroot,
        "readonly_binds": readonly,
        "temp_readonly_binds": readonly_tmp,
        "allow_local_network": allow_network,
        "cpu_seconds": DEFAULT_CPU_SECONDS,
        "fsize_bytes": DEFAULT_FSIZE_BYTES,
        "mem_bytes": _mem_bytes(),
        "nproc": DEFAULT_NPROC,
    }


def wrap(argv: list[str], *, root: str | Path, cwd: str | Path | None = None,
         env: dict[str, str] | None = None, allow_network: bool = False) -> tuple[list[str], dict]:
    """Return (command, environment) that runs ``argv`` inside the sandbox."""
    status = backend()
    if not status.available:
        raise SandboxUnavailable(status.detail)
    root_path = Path(root).resolve()
    working = Path(cwd).resolve() if cwd else root_path
    launcher = Path(tempfile.mkstemp(prefix="babymind-sandbox-", suffix=".py")[1])
    launcher.write_text(LAUNCHER_SOURCE, encoding="utf-8")
    child_env = dict(env or {})
    home = child_env.get("HOME") or ""
    if not home or not Path(home).resolve().is_relative_to(root_path):
        child_env["HOME"] = str(root_path)
    spec = _spec(root_path, working, list(argv), child_env, allow_network)
    command = [
        shutil.which("unshare") or "unshare",
        "--user", "--map-root-user",
        "--mount", "--pid", "--fork", "--kill-child",
        "--propagation", "private",
    ]
    if not allow_network:
        command.append("--net")
    launcher_python = sys.executable
    outer_env = dict(os.environ)
    if getattr(sys, "frozen", False):
        from . import packaged_dev
        launcher_python = str(packaged_dev.python_path())
        outer_env.update(packaged_dev.python_environment())
    command += [launcher_python, str(launcher)]
    outer_env["BABYMIND_SANDBOX_SPEC"] = json.dumps(spec)
    outer_env["BABYMIND_SANDBOX_LAUNCHER"] = str(launcher)
    return command, outer_env


def cleanup(command: list[str], env: dict) -> None:
    """Remove the launcher file and the prepared root after a run."""
    launcher = env.get("BABYMIND_SANDBOX_LAUNCHER")
    if launcher and os.path.exists(launcher):
        try:
            os.unlink(launcher)
        except OSError:
            pass
    raw = env.get("BABYMIND_SANDBOX_SPEC")
    if raw:
        try:
            shutil.rmtree(json.loads(raw).get("newroot", ""), ignore_errors=True)
        except (json.JSONDecodeError, OSError):
            pass


def self_test(root: str | Path | None = None) -> dict:
    """Prove the boundary: probe network, host paths, system writes, workspace writes."""
    status = backend()
    if not status.available:
        return {
            "verified": False,
            "backend": status.name,
            "reason": status.detail,
            "checks": {},
        }
    from . import runner

    project = Path(root or Path.cwd()).resolve()
    try:
        host_network_ns = os.stat("/proc/self/ns/net").st_ino
        # A real sentinel outside the project is needed: HOME is deliberately
        # rewritten inside the sandbox, so probing ~/... proves nothing.
        marker = tempfile.NamedTemporaryFile(prefix=".babymind-isolation-", dir=project.parent)
    except OSError as error:
        return {"verified": False, "backend": status.name, "checks": {},
                "reason": f"Could not create an outside-workspace isolation probe: {error}"}
    marker.write(b"sandbox isolation probe"); marker.flush()
    marker_path = Path(marker.name).resolve()
    if marker_path.is_relative_to(project):
        marker.close()
        return {"verified": False, "backend": status.name, "checks": {},
                "reason": "Could not place the isolation probe outside the project."}
    probe = {
        "network": (
            "import os, socket\n"
            f"print('NAMESPACE_ISOLATED' if os.stat('/proc/self/ns/net').st_ino != {host_network_ns} else 'HOST_NAMESPACE')\n"
            "s = socket.socket(); s.settimeout(3)\n"
            "try:\n"
            "    s.connect(('1.1.1.1', 53)); print('REACHABLE')\n"
            "except OSError as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        ),
        "host_secret": (
            f"target = {str(marker_path)!r}\n"
            "try:\n"
            "    open(target, 'rb').read(); print('READABLE')\n"
            "except OSError:\n"
            "    print('BLOCKED')\n"
        ),
        "system_write": (
            "import os, tempfile\n"
            "try:\n"
            "    fd, p = tempfile.mkstemp(prefix='.babymind-probe-', dir='/usr/bin')\n"
            "    os.close(fd); os.unlink(p); print('WROTE')\n"
            "except OSError as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        ),
        "workspace_write": (
            "import os, tempfile\n"
            "fd, p = tempfile.mkstemp(prefix='.babymind-probe-', dir=os.getcwd())\n"
            "os.write(fd, b'ok'); os.close(fd); os.unlink(p); print('WRITABLE')\n"
        ),
    }
    checks: dict[str, dict] = {}
    try:
        for name, code in probe.items():
            from . import broker
            result = broker.execute(
                [runner.venv_python(), "-c", code], cwd=project, allowed_root=project,
                timeout=60, sandbox_mode=True,
            )
            output = (result.get("stdout", "") + result.get("stderr", "")).strip()
            checks[name] = {
                "output": output[-300:],
                "exit_code": result.get("exit_code"),
                "ok": result.get("ok", False),
            }
    finally:
        marker.close()
    verified = (
        all(check["ok"] for check in checks.values())
        and "NAMESPACE_ISOLATED" in checks["network"]["output"]
        and "BLOCKED" in checks["network"]["output"]
        and "BLOCKED" in checks["host_secret"]["output"]
        and "BLOCKED" in checks["system_write"]["output"]
        and "WRITABLE" in checks["workspace_write"]["output"]
    )
    return {
        "verified": verified,
        "backend": status.name,
        "checks": checks,
        "note": (
            "Each probe ran as a real command inside the sandbox; 'verified' means the kernel "
            "refused the network, the host secret, and the system write while allowing the workspace write."
        ),
    }


def status(probe: bool = False) -> dict:
    record = backend()
    report = {
        "backend": record.name,
        "available": record.available,
        "detail": record.detail,
        "nested_sandbox_detected": nested_sandbox_detected(),
        "mechanisms": {
            "filesystem": "separate mount namespace with a tmpfs root, read-only system binds, "
                          "and only the project directory writable"
            if record.available else "not enforced",
            "network": "separate network namespace (loopback only)" if record.available else "not enforced",
            "process": "separate PID namespace with --kill-child" if record.available else "not enforced",
            "privileges": "unprivileged user namespace; no host capabilities" if record.available else "not enforced",
            "limits": "RLIMIT_CPU / RLIMIT_FSIZE / RLIMIT_NOFILE / RLIMIT_AS + RLIMIT_DATA "
                      "(address-space and data-segment caps) / RLIMIT_NPROC inside the sandbox; "
                      "physical RSS is not capped; any limit the kernel refuses is reported "
                      "on stderr as LIMIT_FAILED"
            if record.available else "not enforced",
            "environment": "rebuilt from a non-secret allowlist",
        },
        "verified": False,
        "evidence": None,
    }
    if probe and record.available:
        evidence = self_test()
        report["verified"] = evidence["verified"]
        report["evidence"] = evidence
    elif record.available:
        report["note"] = "Run the self-test to prove the boundary before relying on it."
    return report
