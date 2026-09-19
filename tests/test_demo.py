import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from config import load_env, redact
from contracts import InvalidAction, load_bundle, projection, validate_action, validate_assignment
from engine import Engine, Inconclusive, check_observation
from executor import NodeExecutor
from models import Observation, WorldSpec
from planner import OpenAIPlanner, RulesPlanner, normalize, wire_schema


class FakeExecutor:
    """Synthetic transition, intentionally unrelated to the real fixture boundary."""
    def __init__(self, threshold=91, flip=False, infra=False):
        self.threshold, self.flip, self.infra = threshold, flip, infra
        self.seen = {}

    def world(self, world_id, factors):
        return WorldSpec(world_id, "node-" + factors["node"], "FAKE UNIT TEST ONLY", factor_values=factors)

    def run_batch(self, batch):
        output = []
        for w in batch.worlds:
            f = w.factor_values
            failure = f["node"] == "26.8.1" and f["allocation"] == "pooled" and f["length"] == "implicit" and f["width"] == 32 and f["size"] < self.threshold
            if self.flip and w.world_id.startswith("confirm"):
                failure = not failure
            status = "FAIL" if failure else "PASS"
            evidence = {**f, "node": "v" + f["node"], "status": status,
                        "backingLength": max(200, f["size"]), "viewLength": None if failure else 1,
                        "error": "synthetic test error" if failure else None}
            output.append(Observation(w.world_id, "ERROR" if self.infra else status, int(failure), json.dumps(evidence), 0.01,
                                      deleted=not self.infra, evidence=evidence))
        return tuple(output)


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle()
        self.events = []

    def engine(self, **kwargs):
        return Engine(self.bundle, kwargs.pop("executor", FakeExecutor()), lambda *a: self.events.append(a),
                      log=lambda _: None, **kwargs)

    def prepared(self, **kwargs):
        e = self.engine(**kwargs)
        e.baseline()
        planner = RulesPlanner(self.bundle)
        e.execute(planner.choose(e.state()))
        return e, planner.choose(e.state())

    def test_quotes_and_bom_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            p = Path(d) / ".env"
            p.write_text('\ufeffDAYTONA_API_KEY="fake-one"\nOPENAI_API_KEY=\'fake-two\'\n', encoding="utf-8")
            load_env(p)
            self.assertEqual(os.environ["DAYTONA_API_KEY"], "fake-one")
            self.assertEqual(os.environ["OPENAI_API_KEY"], "fake-two")
            os.environ["OPENAI_API_KEY"] = "already-set"
            load_env(p)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "already-set")
            self.assertEqual(redact("fake-one already-set"), "[REDACTED] [REDACTED]")

    def test_unknown_env_entry_rejected_without_value_disclosure(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("UNSUPPORTED=secret-value", encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                load_env(p)
            self.assertNotIn("secret-value", str(error.exception))

    def test_initial_projection_withholds_discovered_allocation(self):
        e = self.engine()
        e.baseline()
        self.assertNotIn("backingLength", json.dumps(e.state()))
        e.execute(RulesPlanner(self.bundle).choose(e.state()))
        self.assertIn("backingLength", json.dumps(e.state()))
        self.assertNotIn("backingLength", json.dumps(self.bundle))

    def test_assignment_rejects_commands_boolean_and_unmeasured_node(self):
        f = self.bundle["bad_world"]["factors"]
        for override in ({"size": True}, {"node": "26.8.1; echo unsafe"}, {"node": "26.9.0"},
                         {"backingLength": 100}, {"size": 100001}):
            with self.subTest(override=override), self.assertRaises(InvalidAction):
                validate_assignment({**f, **override}, self.bundle)

    def test_search_discovers_synthetic_answer_and_repeats_endpoints(self):
        e, action = self.prepared()
        e.execute(action)
        self.assertEqual((e.boundary["fail"], e.boundary["pass"]), (90, 91))
        self.assertEqual(len(e.boundary["confirmation_world_ids"]), 10)
        self.assertEqual(len(set(r["world_id"] for r in e.rows)), len(e.rows))
        self.assertEqual(RulesPlanner(self.bundle).choose(e.state())["action"], "STOP")

    def test_boundary_generalizes_to_multiple_unknown_thresholds(self):
        for threshold in (9, 17, 1001, 100000):
            with self.subTest(threshold=threshold):
                e, action = self.prepared(executor=FakeExecutor(threshold))
                e.execute(action)
                self.assertEqual(e.boundary["fail"], threshold - 1)
                self.assertEqual(e.boundary["pass"], threshold)

    def test_unobserved_seed_rejected(self):
        e, action = self.prepared()
        action["values"]["seed_observed_bad"] = 9
        with self.assertRaises(InvalidAction):
            e.execute(action)

    def test_discovered_factor_not_manipulable(self):
        e, action = self.prepared()
        action["factor"] = "backingLength"
        with self.assertRaises(InvalidAction):
            e.execute(action)

    def test_round_one_cannot_jump_to_search(self):
        e, action = self.prepared()
        fresh = self.engine()
        fresh.baseline()
        with self.assertRaises(InvalidAction):
            fresh.execute(action)

    def test_no_pass_bracket_is_inconclusive(self):
        e, action = self.prepared(executor=FakeExecutor(200001))
        with self.assertRaisesRegex(Inconclusive, "No PASS bracket"):
            e.execute(action)
        self.assertIsNone(e.boundary)

    def test_flipped_confirmation_is_inconclusive(self):
        e, action = self.prepared(executor=FakeExecutor(flip=True))
        with self.assertRaisesRegex(Inconclusive, "flipped"):
            e.execute(action)
        self.assertIsNone(e.boundary)

    def test_budget_exhaustion_does_not_guess(self):
        e, action = self.prepared(max_worlds=10)
        with self.assertRaisesRegex(Inconclusive, "budget"):
            e.execute(action)
        self.assertIsNone(e.boundary)
        self.assertLessEqual(e.worlds, 10)

    def test_infrastructure_is_not_a_fixture_failure(self):
        e = self.engine(executor=FakeExecutor(infra=True))
        with self.assertRaises(Inconclusive):
            e.baseline()
        self.assertEqual(e.rows, [])

    def test_bad_evidence_rejected(self):
        from dataclasses import replace
        executor = FakeExecutor()
        w = executor.world("x", self.bundle["bad_world"]["factors"])
        from models import ExperimentBatch
        o = executor.run_batch(ExperimentBatch((w,)))[0]
        bad = [replace(o, exit_code=None), replace(o, exit_code=7), replace(o, deleted=False),
               replace(o, evidence={}), replace(o, world_id="wrong"),
               replace(o, evidence={**o.evidence, "node": "v26.9.0"}),
               replace(o, evidence={**o.evidence, "size": 9}),
               replace(o, evidence={**o.evidence, "status": "PASS"})]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(Inconclusive):
                check_observation(w, row)

    def test_reason_must_reference_previous_evidence(self):
        e, action = self.prepared()
        action["reason"] = "I already know this bug"
        with self.assertRaises(InvalidAction):
            e.execute(action)

    def test_wire_schema_is_strict_and_nullable_fixed_values_normalize(self):
        schema = wire_schema(self.bundle)
        self.assertFalse(schema["additionalProperties"])
        fixed = {k: None for k in self.bundle["bad_world"]["factors"]}
        wire = {"action": "STOP", "factor": [], "fixed": fixed, "reason": "baseline-bad FAIL",
                "values": {"comparisons": [], "seed_observed_bad": None, "min": None, "max": None}}
        self.assertEqual(normalize(wire)["fixed"], {})

    def test_openai_request_response_contract_mock_not_live(self):
        from unittest.mock import Mock
        e = self.engine()
        e.baseline()
        fixed = {k: None for k in self.bundle["bad_world"]["factors"]}
        wire = {"action": "STOP", "factor": [], "fixed": fixed, "reason": "baseline-bad FAIL",
                "values": {"comparisons": [], "seed_observed_bad": None, "min": None, "max": None}}
        response = Mock(status_code=200)
        response.json.return_value = {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(wire)}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}), patch("planner.requests.post", return_value=response) as post:
            planner = OpenAIPlanner(self.bundle, "test-model", lambda *a: self.events.append(a))
            action = planner.choose(e.state())
            self.assertEqual(action["action"], "STOP")
            body = post.call_args.kwargs["json"]
            self.assertFalse(body["store"])
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertNotIn("fake-test-key", json.dumps(body))
            self.assertNotIn("backingLength", body["input"])

    def test_openai_quota_failure_is_one_call_no_silent_fallback(self):
        from unittest.mock import Mock
        response = Mock(status_code=429)
        response.json.return_value = {"error": {"code": "credit_balance_exhausted", "message": "do not log raw bodies"}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}), patch("planner.requests.post", return_value=response) as post:
            planner = OpenAIPlanner(self.bundle, "test-model", lambda *a: self.events.append(a))
            with self.assertRaisesRegex(RuntimeError, "credit_balance_exhausted"):
                planner.choose({})
            self.assertEqual(post.call_count, 1)
            self.assertNotIn("do not log raw bodies", json.dumps(self.events))

    def test_incomplete_or_refused_model_output_is_not_executable(self):
        from unittest.mock import Mock
        for result in ({"status": "incomplete", "output": []}, {"status": "completed", "output": []}):
            response = Mock(status_code=200)
            response.json.return_value = result
            with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}), patch("planner.requests.post", return_value=response):
                with self.assertRaises(RuntimeError):
                    OpenAIPlanner(self.bundle, "test-model", lambda *a: None).choose({})

    def test_wrong_baseline_does_not_start_experiment_loop(self):
        e = self.engine(executor=FakeExecutor(2))
        with self.assertRaisesRegex(Inconclusive, "baseline"):
            e.baseline()

    def test_observed_non_monotonicity_is_inconclusive(self):
        e, action = self.prepared()
        row = copy.deepcopy(e.rows[1])
        row["world_id"] = "synthetic-contradiction"
        row["factors"]["size"] = 4
        row["status"] = "PASS"
        e.rows.append(row)
        with self.assertRaisesRegex(Inconclusive, "single FAIL-to-PASS"):
            e.execute(action)

    def test_compare_rejects_conflicting_fixed_and_unknown_fields(self):
        e = self.engine()
        e.baseline()
        action = RulesPlanner(self.bundle).choose(e.state())
        action["fixed"]["width"] = 32
        with self.assertRaises(InvalidAction):
            e.execute(action)
        action = RulesPlanner(self.bundle).choose(e.state())
        action["shell"] = "untrusted command"
        with self.assertRaises(InvalidAction):
            e.execute(action)


if __name__ == "__main__":
    unittest.main()
