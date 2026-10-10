import unittest
from types import SimpleNamespace

from bridge.benchmark_runtime_cli import run_host_benchmark


class FakeHost:
    instances = []

    def __init__(self, plan):
        self.plan = plan
        self.started = False
        self.stopped = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def wait_until_ready(self, timeout):
        return timeout == 5

    def stop(self):
        self.stopped = True


class FakeRunner:
    def __init__(self, states):
        self.states = list(states)
        self.started = False
        self.closed = False

    def status(self):
        return SimpleNamespace(state="created")

    def start(self):
        self.started = True

    def poll(self):
        return SimpleNamespace(state=self.states.pop(0), reason=None)

    def report(self):
        return {"run_id": "run:fake", "epoch_count": 1, "report_sha256": "a" * 64}

    def close(self):
        self.closed = True


class BenchmarkRuntimeCliTests(unittest.TestCase):
    def setUp(self):
        FakeHost.instances.clear()
        self.plan = SimpleNamespace(host=object())

    def test_runtime_stops_host_and_runner_after_completion(self):
        runner = FakeRunner(["running", "complete"])

        report = run_host_benchmark(
            self.plan,
            {},
            checkpoint_path="checkpoint.json",
            report_path="report.json",
            resume=False,
            host_ready_timeout=5,
            runtime_timeout=10,
            poll_interval=0.01,
            host_factory=FakeHost,
            runner_builder=lambda *_args, **_kwargs: runner,
            clock=lambda: 0,
            sleeper=lambda _seconds: None,
        )

        self.assertEqual(report["run_id"], "run:fake")
        self.assertTrue(runner.started)
        self.assertTrue(runner.closed)
        self.assertTrue(FakeHost.instances[0].started)
        self.assertTrue(FakeHost.instances[0].stopped)

    def test_runtime_timeout_closes_dispatch_and_host(self):
        runner = FakeRunner(["running"])
        times = iter((0.0, 2.0))

        with self.assertRaisesRegex(RuntimeError, "wall-time"):
            run_host_benchmark(
                self.plan,
                {},
                checkpoint_path="checkpoint.json",
                report_path="report.json",
                resume=True,
                host_ready_timeout=5,
                runtime_timeout=1,
                poll_interval=0.01,
                host_factory=FakeHost,
                runner_builder=lambda *_args, **_kwargs: runner,
                clock=lambda: next(times),
                sleeper=lambda _seconds: self.fail("timeout should precede sleep"),
            )

        self.assertTrue(runner.closed)
        self.assertTrue(FakeHost.instances[0].stopped)


if __name__ == "__main__":
    unittest.main()
