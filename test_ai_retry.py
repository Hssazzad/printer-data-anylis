import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_service


class ProviderFailure(Exception):
    def __init__(self, code=503, status="UNAVAILABLE", message="raw provider detail API_KEY=AIzaSyFAKE123"):
        self.code = code
        self.status = status
        self.message = message
        super().__init__(message)


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeChunk:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def _next(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def generate_content(self, **kwargs):
        return self._next()

    def generate_content_stream(self, **kwargs):
        return self._next()


class AIRetryTests(unittest.TestCase):
    def test_unary_retries_transient_failure_then_succeeds(self):
        models = FakeModels([ProviderFailure(), FakeResponse("Recovered answer")])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "warning"):
            answer = ai_service.answer_question("question", {})
        self.assertEqual(answer, "Recovered answer")
        self.assertEqual(models.calls, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_unary_repeated_failure_is_bounded_and_friendly(self):
        models = FakeModels([ProviderFailure() for _ in range(ai_service._MAX_ATTEMPTS)])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "warning"), \
             patch.object(ai_service.logger, "exception"):
            with self.assertRaises(ai_service.AIServiceError) as ctx:
                ai_service.answer_question("question", {})
        self.assertEqual(models.calls, ai_service._MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, ai_service._MAX_ATTEMPTS - 1)
        self.assertIn("temporarily busy", str(ctx.exception))
        self.assertNotIn("raw provider detail", str(ctx.exception))
        self.assertNotIn("AIzaSyFAKE123", str(ctx.exception))
        self.assertNotIn("503", str(ctx.exception))

    def test_google_genai_server_error_is_classified_retryable(self):
        from google.genai import errors

        transient = errors.ServerError(
            503,
            {"error": {"code": 503, "status": "UNAVAILABLE", "message": "provider overloaded"}},
        )
        models = FakeModels([transient, FakeResponse("Recovered")])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "warning"):
            answer = ai_service.answer_question("question", {})
        self.assertEqual(answer, "Recovered")
        self.assertEqual(models.calls, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_unary_non_retryable_error_is_not_retried(self):
        models = FakeModels([ProviderFailure(code=400, status="INVALID_ARGUMENT")])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "exception"):
            with self.assertRaises(ai_service.AIServiceError) as ctx:
                ai_service.answer_question("question", {})
        self.assertEqual(models.calls, 1)
        self.assertEqual(sleep.call_count, 0)
        self.assertNotIn("raw provider detail", str(ctx.exception))

    def test_stream_retries_before_any_output(self):
        models = FakeModels([ProviderFailure(), [FakeChunk("Hello "), FakeChunk("world")]])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "warning"):
            output = list(ai_service.stream_answer_question("question", {}))
        self.assertEqual(output, ["Hello ", "world"])
        self.assertEqual(models.calls, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_stream_does_not_retry_after_partial_output(self):
        def failing_stream():
            yield FakeChunk("Partial answer")
            raise ProviderFailure()

        models = FakeModels([failing_stream()])
        output = []
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "exception"):
            with self.assertRaises(ai_service.AIServiceError) as ctx:
                for chunk in ai_service.stream_answer_question("question", {}):
                    output.append(chunk)
        self.assertEqual(output, ["Partial answer"])
        self.assertEqual(models.calls, 1)
        self.assertEqual(sleep.call_count, 0)
        self.assertIn("temporarily busy", str(ctx.exception))
        self.assertNotIn("raw provider detail", str(ctx.exception))
        self.assertNotIn("AIzaSyFAKE123", str(ctx.exception))

    def test_stream_repeated_failure_is_bounded(self):
        models = FakeModels([ProviderFailure() for _ in range(ai_service._MAX_ATTEMPTS)])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep, \
             patch.object(ai_service.logger, "warning"), \
             patch.object(ai_service.logger, "exception"):
            with self.assertRaises(ai_service.AIServiceError):
                list(ai_service.stream_answer_question("question", {}))
        self.assertEqual(models.calls, ai_service._MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, ai_service._MAX_ATTEMPTS - 1)

    def test_stream_success_keeps_incremental_chunks(self):
        models = FakeModels([[FakeChunk("A"), FakeChunk("B")]])
        with patch.object(ai_service, "_get_client", return_value=SimpleNamespace(models=models)), \
             patch.object(ai_service.time, "sleep") as sleep:
            output = list(ai_service.stream_answer_question("question", {}))
        self.assertEqual(output, ["A", "B"])
        self.assertEqual(models.calls, 1)
        self.assertEqual(sleep.call_count, 0)

    def test_retry_delay_is_exponential_capped_and_jittered(self):
        for attempt in range(8):
            ceiling = min(ai_service._MAX_RETRY_DELAY, ai_service._BASE_RETRY_DELAY * (2 ** attempt))
            delay = ai_service._retry_delay(attempt)
            self.assertGreaterEqual(delay, ceiling / 2)
            self.assertLessEqual(delay, ceiling)

    def test_gemini_client_uses_configured_timeout(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_TIMEOUT_MS": "2500"}, clear=False), \
             patch("google.genai.Client") as client:
            ai_service._get_client()
            self.assertEqual(ai_service._timeout_ms(), 2500)
        self.assertEqual(client.call_args.kwargs["http_options"].timeout, 2500)

        with patch.dict(os.environ, {"GEMINI_TIMEOUT_MS": "not-a-number"}, clear=False):
            self.assertEqual(ai_service._timeout_ms(), 60000)


if __name__ == "__main__":
    unittest.main()
