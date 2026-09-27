#!/usr/bin/env python3
"""Narrow, credential-redacting helper for the ClawMax BodyBrain agents.

Only supports task reads/results and anatomy lookups. It cannot approve or index
records. Task content never controls an origin, HTTP method, or request path.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib import error, parse, request


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(method, path, payload=None):
    base_url = os.environ.get("BODYBRAIN_BACKEND_URL", "").strip().rstrip("/")
    token = os.environ.get("BODYBRAIN_AGENT_TOKEN", "").strip()
    parsed = parse.urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not token
    ):
        raise ValueError("Set BODYBRAIN_BACKEND_URL and BODYBRAIN_AGENT_TOKEN in the agent runtime environment")
    req = request.Request(
        base_url + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with request.build_opener(NoRedirect).open(req, timeout=30) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        raise ValueError("BodyBrain rejected the request (HTTP %d). Review the task and validation requirements." % exc.code) from None
    except (error.URLError, TimeoutError):
        raise ValueError("BodyBrain backend could not be reached. Check the configured runtime URL.") from None
    except (ValueError, UnicodeError):
        raise ValueError("BodyBrain backend returned invalid JSON.") from None
    if not isinstance(result, (dict, list)):
        raise ValueError("BodyBrain backend returned an unexpected result.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("task", help="Fetch task context")
    fetch.add_argument("task_id")
    anatomy = commands.add_parser("anatomy", help="Search the verified atlas catalog")
    anatomy.add_argument("query")
    result = commands.add_parser("result", help="Submit a JSON result file for validation")
    result.add_argument("task_id")
    result.add_argument("json_file", help="Result path; - reads JSON from stdin")
    args = parser.parse_args()
    try:
        if args.command == "anatomy":
            output = send("GET", "/api/agent/anatomy?" + parse.urlencode({"q": args.query}))
        else:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.task_id):
                raise ValueError("Invalid BodyBrain task ID")
            task_path = "/api/agent/tasks/" + args.task_id
            if args.command == "task":
                output = send("GET", task_path)
            else:
                try:
                    text = sys.stdin.read() if args.json_file == "-" else Path(args.json_file).read_text(encoding="utf-8")
                    payload = json.loads(text)
                except (OSError, ValueError, UnicodeError):
                    raise ValueError("Result file must be readable UTF-8 JSON") from None
                if not isinstance(payload, dict):
                    raise ValueError("Task result must be a JSON object")
                output = send("POST", task_path + "/result", payload)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
