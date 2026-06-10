"""Basic HTTP smoke tests for the DocsRAG API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple
from urllib import error, request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run basic HTTP smoke tests.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_URL", "http://127.0.0.1:8000"),
        help="Base URL of the running DocsRAG API.",
    )
    parser.add_argument(
        "--query",
        default="Who are you?",
        help="Simple chat query used for the /chat smoke test.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    health_status, health_payload = http_get_json(f"{base_url}/health", timeout=args.timeout)
    assert_status(health_status, 200, "/health")
    if health_payload.get("status") != "ok":
        raise SystemExit("❌ /health returned unexpected status payload")
    print("✅ /health OK")

    chat_status, chat_payload = http_post_json(
        f"{base_url}/chat",
        payload={"query": args.query},
        timeout=args.timeout,
    )
    assert_status(chat_status, 200, "/chat")
    if not isinstance(chat_payload.get("answer"), str) or not chat_payload.get("answer").strip():
        raise SystemExit("❌ /chat response missing non-empty 'answer' field")
    if "sources" not in chat_payload or not isinstance(chat_payload.get("sources"), list):
        raise SystemExit("❌ /chat response missing 'sources' list field")

    print("✅ /chat OK")
    print(json.dumps(chat_payload, indent=2, ensure_ascii=False))


def http_get_json(url: str, timeout: float) -> Tuple[int, Dict[str, Any]]:
    req = request.Request(url, method="GET")
    return _send_json_request(req, timeout=timeout)


def http_post_json(url: str, payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return _send_json_request(req, timeout=timeout)


def _send_json_request(req: request.Request, timeout: float) -> Tuple[int, Dict[str, Any]]:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        payload = json.loads(body) if body else {}
        return exc.code, payload
    except error.URLError as exc:
        raise SystemExit(f"❌ Request failed: {exc}") from exc


def assert_status(actual: int, expected: int, endpoint: str) -> None:
    if actual != expected:
        raise SystemExit(f"❌ {endpoint} returned HTTP {actual}, expected {expected}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
