from __future__ import annotations

import http.client
import json
import threading
import time

from data_quality_backend.http_server import AgentHTTPServer, AgentRequestHandler, build_demo_orchestrator
from data_quality_backend.planner import HeuristicQueryPlanner
from data_quality_backend.settings import AppSettings


def _start_server() -> tuple[AgentHTTPServer, tuple[str, int]]:
    settings = AppSettings.from_env()
    settings.http_port = 0
    orchestrator = build_demo_orchestrator(settings, query_planner=HeuristicQueryPlanner())
    server = AgentHTTPServer(("127.0.0.1", 0), AgentRequestHandler, orchestrator, settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    return server, server.server_address


def test_http_query_stream_endpoint() -> None:
    server, address = _start_server()
    connection = http.client.HTTPConnection(address[0], address[1], timeout=10)
    try:
        payload = {
            "request_id": "req-stream-1",
            "user_id": "user-1",
            "prompt": "show customers",
            "database_id": "demo-db",
            "stream": True,
        }
        connection.request(
            "POST",
            "/query",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 200
        body = response.read().decode("utf-8")
        assert "event: progress" in body
        assert "event: final" in body
        assert '"ok": true' in body
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
