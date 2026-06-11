from __future__ import annotations

import json
import threading
import time
from urllib.request import Request, urlopen

from data_analysis_backend.http_server import AgentHTTPServer, AgentRequestHandler, build_demo_orchestrator
from data_analysis_backend.planner import HeuristicQueryPlanner
from data_analysis_backend.settings import AppSettings


def _start_server() -> tuple[AgentHTTPServer, str]:
    settings = AppSettings.from_env()
    settings.http_port = 0
    orchestrator = build_demo_orchestrator(settings, query_planner=HeuristicQueryPlanner())
    server = AgentHTTPServer(("127.0.0.1", 0), AgentRequestHandler, orchestrator, settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_http_query_endpoint() -> None:
    server, base_url = _start_server()
    try:
        payload = {
            "request_id": "req-http-1",
            "user_id": "user-1",
            "prompt": "show customers",
            "database_id": "demo-db",
        }
        request = Request(
            f"{base_url}/query",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body["ok"] is True
        assert body["data"]["database_id"] == "demo-db"
        assert body["data"]["result"]["row_count"] == 2
    finally:
        server.shutdown()
        server.server_close()
