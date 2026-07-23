"""Tests for recognition-service lifecycle control (§3.1.6, §3.1.7).

Focuses on the cold-start path: ``restart()`` must bring the engine to a
running state even when it was never started or has been stopped, so the
device page is never a dead end. The HTTP wiring (``/service/restart``
passes the camera URL) is covered end-to-end here.
"""
from __future__ import annotations

import threading

import pytest

from app.core.enums import ServiceState


class _FakeSource:
    """Stand-in FrameSource that does no network I/O.

    ``read()`` returns None so the engine loop spins harmlessly without a
    camera; ``status`` stays OFFLINE so no online/offline system-log side
    effects fire during the test.
    """

    def __init__(self, _url: str, **_kwargs) -> None:
        self.url = _url

    @property
    def status(self):
        from app.core.enums import CameraStatus
        return CameraStatus.OFFLINE

    def read(self):
        # Block very briefly so the loop doesn't busy-spin, then yield no
        # frame — simulating an unreachable camera without opening a socket.
        threading.Event().wait(0.01)
        return None

    def set_url(self, url: str) -> None:
        self.url = url

    def release(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _stop_engine_after():
    """Ensure no engine thread leaks between tests."""
    import app.engine.service as svc
    yield
    svc.service.stop()
    # stop() leaves _camera_url populated; clear it so the next test starts
    # from a truly cold state.
    svc.service._camera_url = None


def test_restart_cold_starts_stopped_engine(monkeypatch):
    """restart() with a URL must start an engine that has no running thread."""
    import app.engine.service as svc
    from tests.fake_provider import NoFaceProvider

    monkeypatch.setattr(svc, "FrameSource", _FakeSource)
    monkeypatch.setattr(svc, "get_provider", lambda: NoFaceProvider())

    svc.service.stop()  # guarantee cold state
    assert svc.service._thread is None
    assert svc.service.state is ServiceState.STOPPED

    svc.service.restart(camera_url="rtsp://test.test/test")

    assert svc.service.state is ServiceState.RUNNING
    assert svc.service._thread is not None
    assert svc.service._thread.is_alive()


def test_restart_without_url_raises_when_cold(monkeypatch):
    """A cold restart with no URL and no prior URL is a configuration error."""
    import app.engine.service as svc

    svc.service.stop()
    svc.service._camera_url = None
    assert svc.service._thread is None

    with pytest.raises(RuntimeError):
        svc.service.restart()


def test_restart_endpoint_recovers_stopped_engine(client, admin_headers, monkeypatch):
    """POST /service/restart brings a stopped engine to running (§3.1.6)."""
    import app.engine.service as svc
    from tests.fake_provider import NoFaceProvider

    monkeypatch.setattr(svc, "FrameSource", _FakeSource)
    monkeypatch.setattr(svc, "get_provider", lambda: NoFaceProvider())

    svc.service.stop()
    assert svc.service._thread is None

    r = client.post("/api/v1/device/service/restart", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["service_state"] == "running"
    assert svc.service.state is ServiceState.RUNNING
    assert svc.service._thread is not None
