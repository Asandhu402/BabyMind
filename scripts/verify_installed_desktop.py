#!/usr/bin/env python3
"""Opt-in smoke test of the installed GUI and its real local model.

Run only in a disposable graphical test environment. The caller must install
python3-websocket, provide DISPLAY (for example via xvfb-run), and pass the
installed executable. Qt remote debugging is bound to loopback for this test;
never enable it in a normal user session.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def wait_for_page(port: int, process: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Desktop exited during startup (status {process.returncode}).")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                pages = json.load(response)
            for page in pages:
                if page.get("type") == "page" and page.get("url", "").startswith("http://127.0.0.1:"):
                    url = page.get("webSocketDebuggerUrl", "")
                    if url.startswith(f"ws://127.0.0.1:{port}/"):
                        return url
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise TimeoutError("Timed out waiting for the installed desktop window.")


class DevTools:
    def __init__(self, url: str):
        # The caller explicitly installs Ubuntu's python3-websocket package.
        from websocket import create_connection
        self.socket = create_connection(url, timeout=30, suppress_origin=True)
        self.sequence = 0

    def call(self, method: str, **params):
        self.sequence += 1
        call_id = self.sequence
        self.socket.send(json.dumps({"id": call_id, "method": method, "params": params}))
        while True:
            result = json.loads(self.socket.recv())
            if result.get("id") == call_id:
                if "error" in result:
                    raise RuntimeError(f"DevTools {method} failed: {result['error']}")
                return result.get("result", {})

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"Desktop JavaScript failed: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def close(self):
        self.socket.close()


def wait_for(condition, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {description}.")


def run(executable: Path, log_path: Path):
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"Installed executable not found or not executable: {executable}")
    # The isolated runner uses this loopback port only for test automation.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{port}"
    env["BABYMIND_MAX_TOKENS"] = "64"
    env["BABYMIND_TEMPERATURE"] = "0"
    env["OMP_NUM_THREADS"] = "2"
    devtools = None
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(executable)], env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            page = wait_for_page(port, process, 600)
            devtools = DevTools(page)
            wait_for(lambda: devtools.evaluate(
                "Boolean(document.querySelector('#chatForm') && "
                "document.querySelector('#sendButton') && "
                "document.querySelector('#messageInput') && document.readyState === 'complete')"
            ), 60, "the chat interface")
            devtools.evaluate("""(() => {
                const input = document.querySelector('#messageInput');
                input.value = 'What is 2 + 2? Answer with the number only.';
                input.dispatchEvent(new Event('input', {bubbles: true}));
                document.querySelector('#sendButton').click();
                return true;
            })()""")
            response = wait_for(lambda: devtools.evaluate("""(() => {
                if (document.querySelector('#sendButton').disabled) return '';
                const messages = document.querySelectorAll('#messages .message-content');
                return messages.length >= 2 ? messages[messages.length - 1].innerText : '';
            })()"""), 600, "the model response")
            print("GUI prompt: What is 2 + 2? Answer with the number only.", flush=True)
            # Escape model-controlled newlines so they cannot inject workflow commands.
            print(f"GUI response: {json.dumps(response, ensure_ascii=True)}", flush=True)
            if "couldn't complete that request" in response.lower():
                raise RuntimeError("The desktop displayed an inference error instead of a response.")
            if not re.fullmatch(r"\s*(?:4|four)[.!]?\s*", response, re.IGNORECASE):
                raise RuntimeError("The response did not contain the expected answer; inspect the recorded output.")
            print("Installed GUI and real-model arithmetic smoke test passed.", flush=True)
            if os.getenv("GITHUB_ACTIONS") == "true":
                safe = response.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                print(f"::notice title=Real-model GUI response::{safe}", flush=True)
        finally:
            if devtools is not None:
                devtools.close()
            # The executable and model server inherit this fresh process group.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.executable, args.log)
    except Exception as error:
        print(f"Desktop verification failed: {json.dumps(str(error), ensure_ascii=True)}", file=sys.stderr)
        if args.log.is_file():
            print("--- Desktop log (last 20,000 characters) ---", file=sys.stderr)
            print(json.dumps(args.log.read_text(encoding="utf-8", errors="replace")[-20000:],
                             ensure_ascii=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
