import json
import tempfile
import unittest
from pathlib import Path

from bridge.provider_adapter_config import load_subprocess_adapter_config


class ProviderAdapterConfigTests(unittest.TestCase):
    def test_loads_explicit_wrappers_without_exposing_environment_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "provider-wrapper"
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o700)
            config = root / "adapters.json"
            config.write_text(
                json.dumps(
                    {
                        "schema": "warband.agentic/subprocess-adapters/v1",
                        "adapters": [
                            {
                                "provider": "provider-a",
                                "argv": ["provider-wrapper", "--json"],
                                "pass_environment": ["PROVIDER_API_KEY"],
                            }
                        ],
                    }
                )
            )

            registry = load_subprocess_adapter_config(
                config,
                required_providers={"provider-a"},
                environ={"PROVIDER_API_KEY": "do-not-retain-in-diagnostics"},
            )

            adapter = registry.adapters["provider-a"]
            self.assertEqual(adapter.argv[0], str(wrapper.resolve()))
            self.assertEqual(
                adapter.environment["PROVIDER_API_KEY"],
                "do-not-retain-in-diagnostics",
            )
            encoded = json.dumps(registry.diagnostics())
            self.assertNotIn("do-not-retain-in-diagnostics", encoded)
            self.assertNotIn("PROVIDER_API_KEY", encoded)
            self.assertNotIn(str(wrapper), encoded)
            self.assertNotIn("do-not-retain-in-diagnostics", repr(adapter))

    def test_rejects_missing_environment_and_provider_without_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper = root / "provider-wrapper"
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o700)
            config = root / "adapters.json"
            config.write_text(
                json.dumps(
                    {
                        "schema": "warband.agentic/subprocess-adapters/v1",
                        "adapters": [
                            {
                                "provider": "provider-a",
                                "argv": [str(wrapper)],
                                "pass_environment": ["PROVIDER_API_KEY"],
                            }
                        ],
                    }
                )
            )

            with self.assertRaisesRegex(ValueError, "environment variable"):
                load_subprocess_adapter_config(config, environ={})
            with self.assertRaisesRegex(ValueError, "required provider"):
                load_subprocess_adapter_config(
                    config,
                    required_providers={"provider-b"},
                    environ={"PROVIDER_API_KEY": "hidden"},
                )


if __name__ == "__main__":
    unittest.main()
