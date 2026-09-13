import json
import time
import unittest
import urllib.request
import urllib.error
from services.api_server import TradingAPIServer


class TestTradingAPIServer(unittest.TestCase):
    def test_trading_api_server_endpoints(self):
        from core.journal import get_journal
        get_journal()._ensure_table()

        port = 8891
        server = TradingAPIServer(port=port)
        server.start()
        time.sleep(0.3)

        try:
            # Test root / discovery index
            req_root = urllib.request.urlopen(f"http://localhost:{port}/")
            self.assertEqual(req_root.status, 200)
            root_data = json.loads(req_root.read().decode("utf-8"))
            self.assertTrue(root_data.get("ok"))
            self.assertEqual(root_data.get("service"), "LastEdge Trading Engine")
            self.assertIn("endpoints", root_data)

            # Test status
            req = urllib.request.urlopen(f"http://localhost:{port}/api/trading/status")
            self.assertEqual(req.status, 200)
            data = json.loads(req.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("service"), "LastEdge Trading Engine")
            self.assertEqual(data.get("status"), "ONLINE")

            # Test health
            req_health = urllib.request.urlopen(f"http://localhost:{port}/api/trading/health")
            self.assertEqual(req_health.status, 200)
            health_data = json.loads(req_health.read().decode("utf-8"))
            self.assertTrue(health_data.get("ok"))

            # Test metrics
            req_metrics = urllib.request.urlopen(f"http://localhost:{port}/api/trading/metrics")
            self.assertEqual(req_metrics.status, 200)
            metrics_data = json.loads(req_metrics.read().decode("utf-8"))
            self.assertTrue(metrics_data.get("ok"))

            # Test positions
            req_pos = urllib.request.urlopen(f"http://localhost:{port}/api/trading/positions")
            self.assertEqual(req_pos.status, 200)
            pos_data = json.loads(req_pos.read().decode("utf-8"))
            self.assertTrue(pos_data.get("ok"))
            self.assertIn("positions", pos_data)

            # Test 404 on unknown endpoint
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(f"http://localhost:{port}/api/unknown_endpoint")
            self.assertEqual(cm.exception.code, 404)

        finally:
            server.stop()
            time.sleep(0.2)


if __name__ == "__main__":
    unittest.main()
