"""DeepSeek-powered browser agent for auto-apply.

Replaces Claude Code CLI with a Python agent that:
1. Starts Playwright MCP server over stdio
2. Uses DeepSeek API (OpenAI-compatible) for decision-making
3. Routes tool calls between DeepSeek and Playwright MCP
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from applypilot import config

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_TURNS = 200
MAX_TOOL_CALLS_PER_TURN = 20

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate to a URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Get the current page as accessible text with element references for interaction",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element by its reference number from the snapshot",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Element reference number (e.g. '42')"}
                },
                "required": ["ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Fill a form field by element reference",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Element reference"},
                    "value": {"type": "string", "description": "Value to fill"},
                },
                "required": ["ref", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill_form",
            "description": "Fill multiple form fields at once. Keys are CSS selectors or field labels, values are the text to fill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": "Dictionary mapping selectors/labels to values",
                        "additionalProperties": {"type": "string"},
                    }
                },
                "required": ["fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select_option",
            "description": "Select an option in a dropdown/select element",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Element reference"},
                    "value": {"type": "string", "description": "Option value or label to select"},
                },
                "required": ["ref", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_take_screenshot",
            "description": "Take a screenshot of the current page",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_evaluate",
            "description": "Run JavaScript in the browser and return the result",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "JavaScript code to execute"}
                },
                "required": ["script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_file_upload",
            "description": "Upload a file using the file input on the page",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to upload",
                    }
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait_for",
            "description": "Wait for a specified time in seconds or for a selector to appear",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to wait for (or leave empty and use time)"},
                    "time": {"type": "number", "description": "Time in seconds to wait if no selector"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_tabs",
            "description": "List, switch, or close browser tabs",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "select", "close"],
                        "description": "Action to perform on tabs",
                    },
                    "tab_index": {
                        "type": "integer",
                        "description": "Tab index to select/close (required for select/close)",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email via Gmail MCP",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths to attach",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]


class MCPClient:
    """Minimal MCP (Model Context Protocol) client over stdio."""

    def __init__(self, port: int, viewport: str = "1280x900"):
        self.port = port
        self.viewport = viewport
        self.proc: subprocess.Popen | None = None
        self._req_id = 0

    def start(self) -> None:
        npx_path = shutil.which("npx") or "npx.cmd"
        cmd = [
            npx_path,
            "@playwright/mcp@latest",
            f"--cdp-endpoint=http://localhost:{self.port}",
            f"--viewport-size={self.viewport}",
        ]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )
        # Initialize MCP session
        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "applypilot-deepseek", "version": "0.1.0"},
        })
        # Notify initialized
        self._notify("notifications/initialized", {})

    def _send(self, msg: dict) -> None:
        if self.proc and self.proc.stdin:
            line = json.dumps(msg) + "\n"
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def _recv(self) -> dict | None:
        if self.proc and self.proc.stdout:
            line = self.proc.stdout.readline()
            if line:
                return json.loads(line.strip())
        return None

    def _request(self, method: str, params: dict) -> dict:
        self._req_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }
        self._send(msg)
        return self._recv()

    def _notify(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send(msg)

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result and "result" in result:
            content = result["result"].get("content", [])
            texts = []
            for c in content:
                if c.get("type") == "text":
                    texts.append(c["text"])
                elif c.get("type") == "image":
                    texts.append("[Screenshot captured]")
            return "\n".join(texts)
        return json.dumps(result) if result else "Tool call failed"

    def stop(self) -> None:
        if self.proc:
            self._request("exit", {})
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class DeepSeekApplyAgent:
    """Browser agent using DeepSeek API + Playwright MCP for auto-apply."""

    def __init__(self, model: str = DEEPSEEK_MODEL):
        config.load_env()
        self.api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY or OPENAI_API_KEY must be set in .env")
        self.model = model
        self.messages: list[dict] = []
        self.turn_count = 0

    def _call_deepseek(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": self.messages,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "max_tokens": 8192,
        }
        resp = httpx.post(DEEPSEEK_API_URL, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def run(self, prompt: str, mcp: MCPClient, dry_run: bool = False) -> tuple[str, int]:
        """Run the agent loop. Returns (status, duration_ms)."""
        start = time.time()

        self.messages = [
            {"role": "system", "content": "You are an autonomous job application agent. You control a browser via tool calls to fill out and submit job applications. Follow the instructions precisely. Use browser_snapshot to see the page, then use other tools to interact with elements."},
            {"role": "user", "content": prompt},
        ]
        self.turn_count = 0

        while self.turn_count < MAX_TURNS:
            self.turn_count += 1

            try:
                response = self._call_deepseek()
            except Exception as e:
                logger.error("DeepSeek API call failed: %s", e)
                elapsed = int((time.time() - start) * 1000)
                return f"failed:api_error_{str(e)[:50]}", elapsed

            choice = response["choices"][0]
            message = choice["message"]

            # Check for RESULT in assistant response text
            if message.get("content"):
                result_match = re.search(
                    r"RESULT:(APPLIED|EXPIRED|CAPTCHA|LOGIN_ISSUE|NEED_LOGIN_HELP|FAILED[:\w]*)",
                    message["content"],
                )
                if result_match:
                    status = result_match.group(1).lower()
                    elapsed = int((time.time() - start) * 1000)
                    return status, elapsed

            # Process tool calls
            if message.get("tool_calls"):
                self.messages.append({
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in message["tool_calls"]
                    ],
                })

                for tc in message["tool_calls"][:MAX_TOOL_CALLS_PER_TURN]:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}

                    logger.debug("[turn %d] Tool call: %s %s", self.turn_count, func_name, func_args)

                    if dry_run and func_name in ("browser_fill", "browser_fill_form", "browser_click", "browser_file_upload"):
                        tool_result = f"[DRY RUN] Would execute: {func_name}({func_args})"
                    else:
                        try:
                            tool_result = mcp.call_tool(func_name, func_args)
                        except Exception as e:
                            tool_result = f"Error calling {func_name}: {e}"

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })
            else:
                # No tool calls — add assistant content and continue
                content = message.get("content") or ""
                if content.strip():
                    self.messages.append({"role": "assistant", "content": content})
                else:
                    # Empty response — break to avoid infinite loop
                    elapsed = int((time.time() - start) * 1000)
                    return "failed:empty_response", elapsed

        elapsed = int((time.time() - start) * 1000)
        return "failed:max_turns", elapsed

    def run_continue(self, mcp: MCPClient, dry_run: bool = False) -> tuple[str, int]:
        """Continue a previous agent session (same messages, different turn counter)."""
        start = time.time()
        self.turn_count = 0

        while self.turn_count < MAX_TURNS:
            self.turn_count += 1

            try:
                response = self._call_deepseek()
            except Exception as e:
                logger.error("DeepSeek API call failed: %s", e)
                elapsed = int((time.time() - start) * 1000)
                return f"failed:api_error_{str(e)[:50]}", elapsed

            choice = response["choices"][0]
            message = choice["message"]

            if message.get("content"):
                result_match = re.search(
                    r"RESULT:(APPLIED|EXPIRED|CAPTCHA|LOGIN_ISSUE|NEED_LOGIN_HELP|FAILED[:\w]*)",
                    message["content"],
                )
                if result_match:
                    status = result_match.group(1).lower()
                    elapsed = int((time.time() - start) * 1000)
                    return status, elapsed

            if message.get("tool_calls"):
                self.messages.append({
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in message["tool_calls"]
                    ],
                })

                for tc in message["tool_calls"][:MAX_TOOL_CALLS_PER_TURN]:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}

                    logger.debug("[cont turn %d] Tool call: %s %s", self.turn_count, func_name, func_args)

                    if dry_run and func_name in ("browser_fill", "browser_fill_form", "browser_click", "browser_file_upload"):
                        tool_result = f"[DRY RUN] Would execute: {func_name}({func_args})"
                    else:
                        try:
                            tool_result = mcp.call_tool(func_name, func_args)
                        except Exception as e:
                            tool_result = f"Error calling {func_name}: {e}"

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })
            else:
                content = message.get("content") or ""
                if content.strip():
                    self.messages.append({"role": "assistant", "content": content})
                else:
                    elapsed = int((time.time() - start) * 1000)
                    return "failed:empty_response", elapsed

        elapsed = int((time.time() - start) * 1000)
        return "failed:max_turns", elapsed
