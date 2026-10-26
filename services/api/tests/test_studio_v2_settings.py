import os
import unittest
from unittest import mock

from daon2_user_api.runtime import RuntimeSettings


class StudioV2SettingsTests(unittest.TestCase):
    def test_default_is_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DAON_STUDIO_V2_ENABLED", None)
            self.assertIs(RuntimeSettings.from_env().studio_v2_enabled, False)

    def test_true_and_false(self):
        for value, expected in (("true", True), ("false", False)):
            with mock.patch.dict(os.environ, {"DAON_STUDIO_V2_ENABLED": value}):
                self.assertIs(RuntimeSettings.from_env().studio_v2_enabled, expected)

    def test_invalid_value_rejected(self):
        for value in ("1", "True", "yes", ""):
            with mock.patch.dict(os.environ, {"DAON_STUDIO_V2_ENABLED": value}):
                with self.assertRaisesRegex(ValueError, "DAON_STUDIO_V2_ENABLED_FLAG_INVALID"):
                    RuntimeSettings.from_env()

    def test_non_bool_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "DAON_STUDIO_V2_ENABLED_FLAG_INVALID"):
            RuntimeSettings(profile="development", bind_host="127.0.0.1", port=8000, studio_v2_enabled="true")


if __name__ == "__main__":
    unittest.main()
