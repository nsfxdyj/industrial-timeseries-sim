"""
tests/test_web_dashboard.py — pytest suite for the web-dashboard output.
"""

import json
import queue
import socket
import threading
import time
import urllib.request

import pytest

from outputs.web_dashboard import WebDashboardOutput, _DashboardHandler


class TestWebDashboardOutput:
    """Integration-ish tests for the SSE dashboard server."""

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_server_starts_and_serves_dashboard(self):
        port = self._free_port()
        out = WebDashboardOutput(host="127.0.0.1", port=port)
        out.open()
        time.sleep(0.3)  # let server start

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
                assert "Industrial Sensor Dashboard" in body
                assert "text/html" in resp.headers.get("Content-Type", "")
        finally:
            out.close()

    def test_sse_endpoint_exists(self):
        port = self._free_port()
        out = WebDashboardOutput(host="127.0.0.1", port=port)
        out.open()
        time.sleep(0.3)

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=3) as resp:
                assert resp.status == 200
                assert "text/event-stream" in resp.headers.get("Content-Type", "")
                # Read initial comment
                line = resp.readline()
                assert line.startswith(b":")
        finally:
            out.close()

    def test_write_broadcasts_to_sse(self):
        port = self._free_port()
        out = WebDashboardOutput(host="127.0.0.1", port=port)
        out.open()
        time.sleep(0.3)

        received = []
        stop_event = threading.Event()

        def reader():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5) as resp:
                    # Skip comment
                    resp.readline()
                    while not stop_event.is_set():
                        line = resp.readline()
                        if not line:
                            break
                        text = line.decode("utf-8").strip()
                        if text.startswith("data:"):
                            received.append(json.loads(text[5:].strip()))
                            break
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(0.2)  # let reader connect

        try:
            out.write({
                "timestamp": "2026-07-30T12:00:00+00:00",
                "sensor": "test_temp",
                "value": 42.5,
                "tags": {"unit": "degC", "location": "lab"},
            })

            stop_event.set()
            t.join(timeout=3)

            assert len(received) == 1
            assert received[0]["sensor"] == "test_temp"
            assert received[0]["value"] == 42.5
        finally:
            out.close()

    def test_multiple_writes_accumulate(self):
        port = self._free_port()
        out = WebDashboardOutput(host="127.0.0.1", port=port)
        out.open()
        time.sleep(0.3)

        received = []
        stop_event = threading.Event()

        def reader():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=5) as resp:
                    resp.readline()  # skip comment
                    while not stop_event.is_set() and len(received) < 5:
                        line = resp.readline()
                        if not line:
                            break
                        text = line.decode("utf-8").strip()
                        if text.startswith("data:"):
                            received.append(json.loads(text[5:].strip()))
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(0.2)  # let reader connect

        try:
            for i in range(5):
                out.write({
                    "timestamp": f"2026-07-30T12:00:0{i}+00:00",
                    "sensor": "test_pressure",
                    "value": float(i),
                    "tags": {"unit": "bar"},
                })
                time.sleep(0.05)

            time.sleep(0.3)
            stop_event.set()
            t.join(timeout=3)

            assert len(received) == 5
            assert [r["value"] for r in received] == [0.0, 1.0, 2.0, 3.0, 4.0]
        finally:
            out.close()

    def test_close_does_not_raise(self):
        """Close must be idempotent and not throw."""
        port = self._free_port()
        out = WebDashboardOutput(host="127.0.0.1", port=port)
        out.open()
        time.sleep(0.2)
        out.close()
        out.close()  # second close should be harmless
        assert True

    def test_full_queue_does_not_crash(self):
        port = self._free_port()
        out = WebDashboardOutput(host="127.0.0.1", port=port)
        out.open()
        time.sleep(0.3)

        try:
            # Fill the queue without any SSE consumer
            for i in range(100):
                out.write({
                    "timestamp": "2026-07-30T12:00:00+00:00",
                    "sensor": "flood",
                    "value": float(i),
                    "tags": {},
                })
            # Should not raise
        finally:
            out.close()
