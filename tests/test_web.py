import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from contracts import load_bundle
from engine import Cancelled, Engine
from history import run_path
from managed_runner import run_one
from models import WorldSpec
from web import RunManager, handler_for
from test_demo import FakeExecutor


def response(body=None, status=200):
    r = Mock(status_code=status)
    r.json.return_value = body or {}
    return r


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.spec = WorldSpec("world-1", "node-26.8.1", "fixed command", factor_values=load_bundle()["bad_world"]["factors"])

    def test_cancel_before_create_does_not_call_service(self):
        stop = threading.Event(); stop.set()
        with patch.dict(os.environ, {"DAYTONA_API_KEY": "test-only"}), patch("managed_runner.requests.post") as post:
            result = run_one(self.spec, run_id="test", emit=lambda *a:self.events.append(a), cancelled=stop)
        post.assert_not_called()
        self.assertEqual(result.status, "ERROR")
        self.assertFalse(result.deleted)

    def test_cancel_after_create_still_deletes_without_execute(self):
        stop = threading.Event()
        def emit(name, data):
            self.events.append((name, data))
            if data["phase"] == "CREATED": stop.set()
        with patch.dict(os.environ, {"DAYTONA_API_KEY": "test-only"}), \
             patch("managed_runner.requests.post", return_value=response({"id":"owned-test", "autoDestroyAt":"2026-09-19T10:00:00Z"})) as post, \
             patch("managed_runner.requests.delete", return_value=response()) as delete:
            result = run_one(self.spec, run_id="test", emit=emit, cancelled=stop)
        self.assertTrue(result.deleted)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["ttlMinutes"], 15)
        delete.assert_called_once()
        self.assertTrue(delete.call_args.args[0].endswith("owned-test"))

    def test_missing_ttl_acknowledgement_fails_closed_and_deletes(self):
        with patch.dict(os.environ, {"DAYTONA_API_KEY": "test-only"}), \
             patch("managed_runner.requests.post", return_value=response({"id":"owned-test"})) as post, \
             patch("managed_runner.requests.get", return_value=response({"id":"owned-test"})), \
             patch("managed_runner.requests.delete", return_value=response()):
            result = run_one(self.spec, run_id="test", emit=lambda *a:None, cancelled=threading.Event())
        self.assertEqual(post.call_count, 1)
        self.assertTrue(result.deleted)
        self.assertIn("TTL", result.error)

    def test_cleanup_failure_not_reported_destroyed(self):
        deleted = response(); deleted.raise_for_status.side_effect=RuntimeError("simulated delete failure")
        evidence={"status":"PASS"}
        with patch.dict(os.environ, {"DAYTONA_API_KEY":"test-only"}), \
             patch("managed_runner.requests.post", side_effect=[response({"id":"owned-test","autoDestroyAt":"test"}),response({"exitCode":0,"result":json.dumps(evidence)})]), \
             patch("managed_runner.requests.delete", return_value=deleted):
            result=run_one(self.spec,run_id="test",emit=lambda *a:self.events.append(a),cancelled=threading.Event())
        self.assertFalse(result.deleted)
        self.assertEqual(result.status,"ERROR")
        self.assertIn("CLEANUP_FAILED",[e[1]["phase"] for e in self.events])

    def test_engine_cancel_does_not_launch_next_batch(self):
        stopped=threading.Event(); stopped.set()
        executor=FakeExecutor()
        engine=Engine(load_bundle(),executor,lambda *a:None,cancelled=stopped)
        with self.assertRaises(Cancelled): engine.baseline()
        self.assertEqual(engine.worlds,0)

    def test_cancellation_retains_completed_batch_observations(self):
        stopped=threading.Event()
        class CancelAfterBatch(FakeExecutor):
            def run_batch(self,batch):
                observations=super().run_batch(batch); stopped.set(); return observations
        engine=Engine(load_bundle(),CancelAfterBatch(),lambda *a:None,log=lambda *a:None,cancelled=stopped)
        with self.assertRaises(Cancelled): engine.baseline()
        self.assertEqual(len(engine.rows),2)


class ManagerTests(unittest.TestCase):
    def test_history_path_rejects_traversal(self):
        for name in ("../.env",".env","anything","20260919-000000-abcdef/../"):
            with self.assertRaises(ValueError):run_path(name)

    def test_run_options_reject_commands_or_excessive_budget(self):
        manager=RunManager()
        for value in ({"shell":"anything"},{"max_worlds":10000},{"max_worlds":True},{"seconds":0},{"planner":"anything"},{"source_world":"baseline-bad"},{"source_run":"20260919-144400-5b5cea"}):
            with self.assertRaises(ValueError):manager.start(value)

    def test_duplicate_start_and_shutdown(self):
        release=threading.Event(); entered=threading.Event()
        def fake_execute(*args,**kwargs):
            entered.set(); release.wait(3)
        with patch("web.execute",side_effect=fake_execute),patch("web.NodeExecutor"),patch.dict(os.environ,{"OPENAI_API_KEY":"test-only"}):
            manager=RunManager(); identifier=manager.start({"planner":"rules"}); self.assertTrue(entered.wait(1))
            try:
                with self.assertRaises(RuntimeError):manager.start({"planner":"rules"})
                with self.assertRaises(ValueError):manager.stop("not-the-active-run")
                manager.stop(identifier);self.assertTrue(manager.cancelled.is_set())
                manager.shutdown()
            finally:
                release.set();manager.worker.join(3)
            with self.assertRaises(RuntimeError):manager.start({"planner":"rules"})


if __name__=='__main__':unittest.main()
