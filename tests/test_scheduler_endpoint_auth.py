import os
import unittest

os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = ""

from fastapi import HTTPException

import app.main as main


class SchedulerEndpointAuthTests(unittest.TestCase):
    def test_scheduler_token_is_required_even_when_not_configured(self):
        original_token = main.settings.scheduler_endpoint_token
        try:
            main.settings.scheduler_endpoint_token = ""

            with self.assertRaises(HTTPException) as ctx:
                main._require_scheduler_token(None)

            self.assertEqual(ctx.exception.status_code, 503)
        finally:
            main.settings.scheduler_endpoint_token = original_token

    def test_scheduler_token_rejects_invalid_value(self):
        original_token = main.settings.scheduler_endpoint_token
        try:
            main.settings.scheduler_endpoint_token = "expected-token"

            with self.assertRaises(HTTPException) as ctx:
                main._require_scheduler_token("wrong-token")

            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            main.settings.scheduler_endpoint_token = original_token

    def test_scheduler_token_accepts_matching_value(self):
        original_token = main.settings.scheduler_endpoint_token
        try:
            main.settings.scheduler_endpoint_token = "expected-token"

            main._require_scheduler_token("expected-token")
        finally:
            main.settings.scheduler_endpoint_token = original_token


if __name__ == "__main__":
    unittest.main()
