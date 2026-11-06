#!/usr/bin/env python3
"""Smoke test of the installed GUI and its real local model.

CI runs this on every push and pull request. Use only a disposable graphical
test environment: the caller must install python3-websocket, provide DISPLAY
(for example via xvfb-run), and pass the installed executable. Qt remote
debugging is bound to loopback for this test; never enable it in a normal user
session.
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


# Each tuple is (question, exact-answer pattern or None for manual review,
# start a fresh conversation). The final pair tests short-term chat context.
EXTENDED_QUESTIONS = [
    ("What is 15 plus 27? Answer with the number only.", r"42", True),
    ("What is 9 multiplied by 7? Answer with the number only.", r"63", True),
    ("What is 120 divided by 4? Answer with the number only.", r"30", True),
    ("What comes next: 2, 4, 8, 16? Answer with the number only.", r"32", True),
    ("I have 7 apples and give away 3. How many remain? Answer with the number only.", r"4|four", True),
    ("What is the capital of France? Answer with one word.", r"paris", True),
    ("At standard pressure, at what Celsius temperature does water freeze? Answer with the number only.", r"0|zero", True),
    ("If today is Monday, what day is it three days later? Answer with one word.", r"thursday", True),
    ("Reverse the letters in the word dog. Answer with the reversed word only.", r"god", True),
    ("Write a short Python function add(a, b) that returns their sum. Return code only.", None, True),
    ("In one sentence, explain why keeping backups matters.", None, True),
    ("Can you see files on my computer that I have not shared? Answer honestly in one sentence.", None, True),
    ("Remember the code word ORBIT for my next question. Reply READY only.", r"ready", True),
    ("What was the code word I just asked you to remember? Reply with only the word.", r"orbit", False),
]


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


def run_extended_chat(devtools: DevTools, report_path: Path) -> dict:
    results = []
    expected_messages = 0
    for index, (question, pattern, fresh) in enumerate(EXTENDED_QUESTIONS, 1):
        if fresh:
            expected_messages = 0
        expected_messages += 2
        send = (
            "(() => { " + ("document.querySelector('#newChat').click(); " if fresh else "")
            + "const input=document.querySelector('#messageInput'); input.value=" + json.dumps(question)
            + "; input.dispatchEvent(new Event('input', {bubbles:true})); "
            "document.querySelector('#sendButton').click(); return true; })()"
        )
        record = {"number": index, "question": question, "response": "", "assessment": "error"}
        try:
            devtools.evaluate(send)
            response = wait_for(lambda: devtools.evaluate(
                "(() => { if(document.querySelector('#sendButton').disabled) return ''; "
                "const messages=document.querySelectorAll('#messages .message-content'); "
                f"return messages.length >= {expected_messages} ? messages[messages.length-1].innerText : ''; }})()"
            ), 600, f"answer to question {index}")
            record["response"] = response
            if "couldn't complete that request" in response.lower():
                record["assessment"] = "app error"
            elif pattern is None:
                record["assessment"] = "manual review"
            elif re.fullmatch(r"\s*(?:" + pattern + r")[.!]?\s*", response, re.IGNORECASE):
                record["assessment"] = "matched expected answer"
            else:
                record["assessment"] = "incorrect or format mismatch"
        except Exception as error:
            record["error"] = str(error)
            results.append(record)
            report_path.write_text(json.dumps({"results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
            break
        results.append(record)
        print(f"QUESTION {index}: {json.dumps(record, ensure_ascii=True)}", flush=True)
        report_path.write_text(json.dumps({"results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

    for start in range(0, len(results), 4):
        group = results[start:start + 4]
        text = "\n".join(f"Q{r['number']}: {r['question']}\nAnswer: {r['response'][:600]}\nAssessment: {r['assessment']}"
                         for r in group)
        if os.getenv("GITHUB_ACTIONS") == "true":
            safe = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::notice title=GUI questions {start + 1}-{start + len(group)}::{safe}", flush=True)
    counts = {status: sum(r["assessment"] == status for r in results) for status in
              ("matched expected answer", "incorrect or format mismatch", "manual review", "app error", "error")}
    report = {"results": results, "counts": counts, "requested": len(EXTENDED_QUESTIONS)}
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("GUI question summary: " + json.dumps(counts), flush=True)
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("::notice title=GUI question summary::" + json.dumps(counts), flush=True)
    return report


def run(executable: Path, log_path: Path, *, extended: bool = False, report_path: Path | None = None):
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"Installed executable not found or not executable: {executable}")
    # The isolated runner uses this loopback port only for test automation.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{port}"
    env["BABYMIND_MAX_TOKENS"] = "160" if extended else "64"
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
            if extended:
                if report_path is None:
                    raise ValueError("An extended-chat report path is required.")
                report = run_extended_chat(devtools, report_path)
                counts = report["counts"]
                if (len(report["results"]) != report["requested"] or counts["incorrect or format mismatch"]
                        or counts["app error"] or counts["error"]):
                    raise RuntimeError("Some extended GUI questions failed or did not match their requested answer format.")
                return report
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
    parser.add_argument("--extended-chat", action="store_true")
    parser.add_argument("--report", type=Path, help="JSON report for --extended-chat")
    args = parser.parse_args()
    if args.extended_chat and not args.report:
        parser.error("--report is required with --extended-chat")
    try:
        run(args.executable, args.log, extended=args.extended_chat, report_path=args.report)
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
