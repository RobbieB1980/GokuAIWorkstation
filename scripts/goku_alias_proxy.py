#!/usr/bin/env python3
"""Thin OpenAI-compatible proxy: Goku aliases -> Mia serve_openai backend."""
from __future__ import annotations

import argparse
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALIASES = {
    "goku-fast",
    "goku-code",
    "goku-heavy",
    "goku-research",
    "goku-reviewer",
}


class State:
    def __init__(self, backend: str):
        self.backend = backend.rstrip("/")
        self.lock = threading.Lock()
        self.upstream_model: str | None = None

    @property
    def backend_root(self) -> str:
        # Mia serves /health at server root, not under /v1.
        if self.backend.endswith("/v1"):
            return self.backend[:-3]
        return self.backend


def _request(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 600.0):
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        if k.lower() == "host":
            continue
        req.add_header(k, v)
    if body is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, dict(resp.headers.items()), resp.read()


def discover_model(state: State) -> str:
    with state.lock:
        if state.upstream_model:
            return state.upstream_model
    status, _, raw = _request("GET", f"{state.backend}/models", timeout=30.0)
    if status >= 400:
        raise RuntimeError(f"backend /models failed: HTTP {status}")
    payload = json.loads(raw.decode("utf-8"))
    data = payload.get("data") or []
    if not data:
        raise RuntimeError("backend /models returned no models")
    model_id = data[0].get("id")
    if not model_id:
        raise RuntimeError("backend model entry missing id")
    with state.lock:
        state.upstream_model = model_id
    return model_id


def rewrite_model(state: State, payload: dict) -> dict:
    """Rewrite goku-* aliases and always force thinking off for local workers."""
    payload = dict(payload)
    model = payload.get("model")
    if isinstance(model, str) and model in ALIASES:
        payload["model"] = discover_model(state)
    # GrokBuild orchestrates. Local workers must not burn context on hidden reasoning.
    # serve_openai reads chat_template_kwargs.enable_thinking, then body.enable_thinking.
    template_kwargs = payload.get("chat_template_kwargs")
    if not isinstance(template_kwargs, dict):
        template_kwargs = {}
    else:
        template_kwargs = dict(template_kwargs)
    template_kwargs["enable_thinking"] = False
    payload["chat_template_kwargs"] = template_kwargs
    payload["enable_thinking"] = False
    return payload


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            print(f"[goku-proxy] {self.address_string()} - {fmt % args}")

        def _send(self, status: int, headers: dict, body: bytes):
            self.send_response(status)
            for k, v in headers.items():
                lk = k.lower()
                if lk in ("transfer-encoding", "connection", "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _normalize_path(self, path: str) -> str:
            # Avoid /v1/v1/... when backend already ends with /v1.
            if state.backend.endswith("/v1") and path.startswith("/v1/"):
                return path[3:]
            if state.backend.endswith("/v1") and path == "/v1":
                return "/"
            return path

        def _proxy(self, path: str, rewrite_json: bool = False):
            path = self._normalize_path(path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items()}
            if rewrite_json and body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    payload = rewrite_model(state, payload)
                    body = json.dumps(payload).encode("utf-8")
                    headers["Content-Length"] = str(len(body))
                except Exception as exc:
                    err = json.dumps({"error": {"message": f"proxy rewrite failed: {exc}", "type": "goku_proxy_error"}}).encode()
                    self._send(500, {"Content-Type": "application/json"}, err)
                    return

            # Streaming: pass through raw bytes without buffering whole body when stream=true
            stream = False
            if body:
                try:
                    stream = bool(json.loads(body.decode("utf-8")).get("stream"))
                except Exception:
                    stream = False

            url = f"{state.backend}{path}"
            try:
                req = urllib.request.Request(url, data=body, method=self.command)
                for k, v in headers.items():
                    if k.lower() in ("host", "content-length"):
                        continue
                    req.add_header(k, v)
                if body is not None:
                    req.add_header("Content-Length", str(len(body)))
                    if "Content-Type" not in headers:
                        req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=600.0) as resp:
                    if stream:
                        self.send_response(resp.status)
                        for k, v in resp.headers.items():
                            if k.lower() in ("transfer-encoding", "connection", "content-length"):
                                continue
                            self.send_header(k, v)
                        self.send_header("Connection", "close")
                        self.end_headers()
                        while True:
                            chunk = resp.read(8192)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        return
                    raw = resp.read()
                    self._send(resp.status, dict(resp.headers.items()), raw)
            except urllib.error.HTTPError as exc:
                raw = exc.read() if exc.fp else b""
                self._send(exc.code, {"Content-Type": "application/json"}, raw or json.dumps({"error": str(exc)}).encode())
            except Exception as exc:
                err = json.dumps({"error": {"message": str(exc), "type": "goku_proxy_error"}}).encode()
                self._send(502, {"Content-Type": "application/json"}, err)

        def do_GET(self):
            if self.path in ("/health", "/v1/health"):
                try:
                    status, headers, raw = _request("GET", f"{state.backend_root}/health", timeout=10.0)
                    # Also advertise proxy health
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except Exception:
                        payload = {"backend_raw": raw.decode("utf-8", errors="replace")}
                    payload["goku_proxy"] = "ok"
                    payload["backend"] = state.backend
                    try:
                        payload["upstream_model"] = discover_model(state)
                    except Exception as exc:
                        payload["upstream_model_error"] = str(exc)
                    body = json.dumps(payload).encode("utf-8")
                    self._send(200 if status < 400 else status, {"Content-Type": "application/json"}, body)
                except Exception as exc:
                    body = json.dumps({"goku_proxy": "ok", "backend": state.backend, "backend_error": str(exc)}).encode()
                    self._send(503, {"Content-Type": "application/json"}, body)
                return
            if self.path.startswith("/v1/models") or self.path == "/models":
                try:
                    upstream = discover_model(state)
                    data = [{"id": alias, "object": "model", "owned_by": "gokuai"} for alias in sorted(ALIASES)]
                    data.insert(0, {"id": upstream, "object": "model", "owned_by": "mia-backend"})
                    body = json.dumps({"object": "list", "data": data}).encode("utf-8")
                    self._send(200, {"Content-Type": "application/json"}, body)
                except Exception as exc:
                    body = json.dumps({"error": {"message": str(exc), "type": "goku_proxy_error"}}).encode()
                    self._send(502, {"Content-Type": "application/json"}, body)
                return
            self._proxy(self.path)

        def do_POST(self):
            if "/chat/completions" in self.path or self.path.endswith("/completions"):
                self._proxy(self.path, rewrite_json=True)
                return
            self._proxy(self.path, rewrite_json=True)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11437)
    ap.add_argument("--backend", default="http://127.0.0.1:8888/v1")
    args = ap.parse_args()
    state = State(args.backend)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"[goku-proxy] listening on http://{args.host}:{args.port}/v1 -> {state.backend}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
