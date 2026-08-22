import json
import time
import urllib.request
import pytest
from services.api_server import TradingAPIServer


def test_trading_api_server_endpoints():
    from core.journal import get_journal
    get_journal()._ensure_table()

    port = 8891
    server = TradingAPIServer(port=port)
    server.start()
    time.sleep(0.3)

    try:
        # Test status
        req = urllib.request.urlopen(f"http://localhost:{port}/api/trading/status")
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert data.get("ok") is True
        assert data.get("service") == "LastEdge Trading Engine"
        assert data.get("status") == "ONLINE"

        # Test health
        req_health = urllib.request.urlopen(f"http://localhost:{port}/api/trading/health")
        assert req_health.status == 200
        health_data = json.loads(req_health.read().decode("utf-8"))
        assert health_data.get("ok") is True

        # Test metrics
        req_metrics = urllib.request.urlopen(f"http://localhost:{port}/api/trading/metrics")
        assert req_metrics.status == 200
        metrics_data = json.loads(req_metrics.read().decode("utf-8"))
        assert metrics_data.get("ok") is True

        # Test positions
        req_pos = urllib.request.urlopen(f"http://localhost:{port}/api/trading/positions")
        assert req_pos.status == 200
        pos_data = json.loads(req_pos.read().decode("utf-8"))
        assert pos_data.get("ok") is True
        assert "positions" in pos_data

        # Test 404 on unknown endpoint
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://localhost:{port}/api/unknown_endpoint")
        assert exc_info.value.code == 404

    finally:
        server.stop()
        time.sleep(0.2)
