import asyncio
import json
import unittest
from unittest.mock import patch

from starlette.requests import Request

import main

CONTEXT = {
    "provenance": {
        "as_of": "2026-11-13",
        "sales_period": {"from": "2025-12", "to": "2026-11"},
        "missing_months": ["2026-02"],
        "data_is_stale": False,
    },
    "forecast_readiness": {"sufficient": True},
    "forecast_three_month": {"status": "ok"},
}


def make_request(body=b"", path="/api/ai/chat"):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 1234),
        "server": ("test", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def response_json(response):
    if isinstance(response, dict):
        return response
    return json.loads(response.body)


class AIEndpointTests(unittest.TestCase):
    def test_ai_endpoints_require_authentication(self):
        calls = [
            (main.ai_chat, (make_request(b'{"message":"hi"}'),)),
            (main.ai_insights, (make_request(b"", "/api/ai/insights"),)),
            (main.ai_forecast, (make_request(b"", "/api/ai/forecast"),)),
            (main.ai_stream, ("chat", make_request(b'{"message":"hi"}', "/api/ai/chat/stream"))),
        ]
        for endpoint, args in calls:
            response = asyncio.run(endpoint(*args))
            self.assertEqual(response.status_code, 401)

    def test_chat_rejects_invalid_or_non_object_json(self):
        with patch.object(main, "require_ai_auth", return_value=None):
            for body in (b"{bad", b"[]", b"{}"):
                response = asyncio.run(main.ai_chat(make_request(body)))
                self.assertEqual(response.status_code, 422)
            too_long = json.dumps({"message": "x" * 2001}).encode()
            response = asyncio.run(main.ai_chat(make_request(too_long)))
            self.assertEqual(response.status_code, 422)

    def test_chat_success_includes_freshness_metadata(self):
        with patch.object(main, "require_ai_auth", return_value=None), \
             patch.object(main, "build_business_context", return_value=CONTEXT), \
             patch.object(main, "answer_question", return_value="Read-only answer"):
            response = asyncio.run(main.ai_chat(make_request(b'{"message":"hi"}')))
        self.assertEqual(response["answer"], "Read-only answer")
        self.assertEqual(response["metadata"]["sales_period"]["to"], "2026-11")
        self.assertEqual(response["metadata"]["missing_months"], ["2026-02"])
        self.assertTrue(response["metadata"]["forecast_is_directional"])

    def test_insights_and_forecast_include_metadata(self):
        endpoints = [
            (main.ai_insights, "generate_insights", make_request(b"", "/api/ai/insights")),
            (main.ai_forecast, "generate_forecast", make_request(b"", "/api/ai/forecast")),
        ]
        for endpoint, generator_name, request in endpoints:
            with patch.object(main, "require_ai_auth", return_value=None), \
                 patch.object(main, "build_business_context", return_value=CONTEXT), \
                 patch.object(main, generator_name, return_value="Generated answer"):
                response = asyncio.run(endpoint(request))
            self.assertEqual(response["answer"], "Generated answer")
            self.assertEqual(response["metadata"]["as_of"], "2026-11-13")

    def test_context_failure_returns_generic_503(self):
        with patch.object(main, "require_ai_auth", return_value=None), \
             patch.object(main, "build_business_context", side_effect=RuntimeError("db password leak")), \
             patch.object(main.logger, "exception"):
            response = asyncio.run(main.ai_chat(make_request(b'{"message":"hi"}')))
        self.assertEqual(response.status_code, 503)
        payload = response_json(response)
        self.assertEqual(payload["message"], "Could not prepare business data.")
        self.assertNotIn("password", payload["message"])

    def test_provider_errors_are_actionable_and_do_not_leak_details(self):
        with patch.object(main, "require_ai_auth", return_value=None), \
             patch.object(main, "build_business_context", return_value=CONTEXT), \
             patch.object(main, "answer_question", side_effect=main.AIServiceError("The AI service is temporarily busy. Please try again.")):
            response = asyncio.run(main.ai_chat(make_request(b'{"message":"hi"}')))
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily busy", response_json(response)["message"])

        with patch.object(main, "require_ai_auth", return_value=None), \
             patch.object(main, "build_business_context", return_value=CONTEXT), \
             patch.object(main, "answer_question", side_effect=RuntimeError("API_KEY=AIzaSyFAKE123")), \
             patch.object(main.logger, "exception"):
            response = asyncio.run(main.ai_chat(make_request(b'{"message":"hi"}')))
        self.assertEqual(response.status_code, 500)
        payload = response_json(response)
        self.assertEqual(payload["message"], "AI request failed.")
        self.assertNotIn("AIzaSyFAKE123", payload["message"])

    def test_stream_emits_metadata_before_deltas_and_done(self):
        async def consume():
            response = await main.ai_stream("chat", make_request(b'{"message":"hi"}', "/api/ai/chat/stream"))
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return response, chunks

        with patch.object(main, "require_ai_auth", return_value=None), \
             patch.object(main, "build_business_context", return_value=CONTEXT), \
             patch.object(main, "stream_answer_question", return_value=iter(["A", "B"])):
            response, chunks = asyncio.run(consume())
        self.assertEqual(response.status_code, 200)
        events = [json.loads(chunk[len("data: "):].strip()) for chunk in chunks]
        self.assertEqual(events[0]["meta"]["sales_period"]["to"], "2026-11")
        self.assertEqual([event.get("delta") for event in events[1:3]], ["A", "B"])
        self.assertTrue(events[-1]["done"])

    def test_stream_validation_and_context_failure(self):
        with patch.object(main, "require_ai_auth", return_value=None):
            unknown = asyncio.run(main.ai_stream("bogus", make_request(b"", "/api/ai/bogus/stream")))
            self.assertEqual(unknown.status_code, 404)

            invalid = asyncio.run(main.ai_stream("chat", make_request(b"{bad", "/api/ai/chat/stream")))
            self.assertEqual(invalid.status_code, 422)

            with patch.object(main, "build_business_context", side_effect=RuntimeError("db down")), \
                 patch.object(main.logger, "exception"):
                failed = asyncio.run(main.ai_stream("insights", make_request(b"", "/api/ai/insights/stream")))
            self.assertEqual(failed.status_code, 503)

    def test_stream_provider_error_is_an_sse_event(self):
        def broken_stream():
            raise main.AIServiceError("The AI service is temporarily busy. Please try again.")
            yield

        async def consume():
            response = await main.ai_stream("insights", make_request(b"", "/api/ai/insights/stream"))
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return chunks

        with patch.object(main, "require_ai_auth", return_value=None), \
             patch.object(main, "build_business_context", return_value=CONTEXT), \
             patch.object(main, "stream_insights", return_value=broken_stream()):
            chunks = asyncio.run(consume())
        events = [json.loads(chunk[len("data: "):].strip()) for chunk in chunks]
        self.assertIn("meta", events[0])
        self.assertIn("temporarily busy", events[-1]["error"])


if __name__ == "__main__":
    unittest.main()
