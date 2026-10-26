import unittest
from contextlib import contextmanager

from daon2_user_api.model_selection import ModelSelectionError, probe_reasoning_levels
from daon2_user_api.workspace_model_defaults import ResolvedModel


class FakeService:
    def __init__(self):
        self.confirmed = None

    def confirm_reasoning_levels(self, tenant_id, actor_id, connection_id, model_id, levels):
        self.confirmed = (connection_id, model_id, list(levels))


class FakeResolver:
    def __init__(self, provider="UPSTAGE", adapter=""):
        self.provider, self.adapter = provider, adapter

    @contextmanager
    def resolve(self, context, capability, *, connection_id=None, model_id=None):
        model = ResolvedModel(connection_id=connection_id, provider_code=self.provider, model_id=model_id, capability=capability,
                              base_url="https://api.example/v1", credential_version=1, default_version=1, catalog_version=1,
                              provider_kind="external_api", routing_owner="provider", daon_fallback_allowed=False,
                              _credential=bytearray(b"k"), adapter_type=self.adapter)
        try:
            yield model
        finally:
            model.release()


class FakeTransport:
    """low·high만 받아 주고 none·medium은 거부하는 모델."""
    def __init__(self, baseline_fails=False):
        self.payloads, self.baseline_fails = [], baseline_fails

    def post_json(self, **kwargs):
        payload = kwargs["payload"]
        self.payloads.append((kwargs["url"], payload))
        level = payload.get("reasoning_effort") or (payload.get("reasoning") or {}).get("effort")
        if level is None and self.baseline_fails:
            raise ValueError("down")
        if level in ("none", "medium"):
            error = ValueError("bad"); error.code = "PROVIDER_REQUEST_REJECTED"; raise error
        return {"usage": {"completion_tokens_details": {"reasoning_tokens": 7 if level == "high" else 0}}}


class ProbeTests(unittest.TestCase):
    def run_probe(self, resolver, transport, service):
        return probe_reasoning_levels(service, resolver, transport, tenant_id="t", workspace_id="w", actor_id="a", connection_id="c", model_id="m")

    def test_only_accepted_levels_are_confirmed(self):
        service, transport = FakeService(), FakeTransport()
        result = self.run_probe(FakeResolver(), transport, service)
        self.assertEqual(result["confirmed"], ["low", "high"])
        self.assertEqual(service.confirmed, ("c", "m", ["low", "high"]))
        self.assertEqual(result["results"]["medium"], {"accepted": False, "code": "PROVIDER_REQUEST_REJECTED"})
        self.assertEqual(result["results"]["high"]["reasoning_tokens"], 7)
        self.assertEqual(transport.payloads[0][0], "https://api.example/v1/chat/completions")
        self.assertNotIn("reasoning_effort", transport.payloads[0][1], "첫 요청은 수준 없는 기준 요청이다")

    def test_omniroute_uses_the_responses_api_shape(self):
        transport = FakeTransport()
        self.run_probe(FakeResolver("OMNIROUTE"), transport, FakeService())
        self.assertTrue(transport.payloads[1][0].endswith("/v1/responses"))
        self.assertEqual(transport.payloads[-1][1]["reasoning_effort"], "high")

    def test_a_model_that_does_not_answer_at_all_confirms_nothing(self):
        service = FakeService()
        with self.assertRaises(ModelSelectionError) as caught:
            self.run_probe(FakeResolver(), FakeTransport(baseline_fails=True), service)
        self.assertEqual(caught.exception.code, "MODEL_PROBE_FAILED")
        self.assertIsNone(service.confirmed)

    def test_unsupported_provider_is_refused_without_a_call(self):
        transport = FakeTransport()
        for resolver in (FakeResolver("OLLAMA"), FakeResolver("CUSTOM", "anthropic_compatible")):
            with self.assertRaises(ModelSelectionError) as caught:
                self.run_probe(resolver, transport, FakeService())
            self.assertEqual(caught.exception.code, "REASONING_PROVIDER_UNSUPPORTED")
        self.assertEqual(transport.payloads, [])


if __name__ == "__main__":
    unittest.main()


class RouterTests(unittest.TestCase):
    def test_routers_always_offer_exactly_low_medium_high(self):
        from daon2_user_api.model_selection import ROUTER_REASONING_LEVELS, is_reasoning_router
        self.assertEqual(ROUTER_REASONING_LEVELS, ("low", "medium", "high"))
        for provider, url in (("OMNIROUTE", "https://x/v1"), ("EOUL_GATEWAY", "https://x"), ("OPENROUTER", "https://openrouter.ai/api/v1"),
                              ("CUSTOM", "https://media-bridge-gateway.sinsan.kr/v1")):
            self.assertTrue(is_reasoning_router(provider, url), provider)
        for provider, url in (("UPSTAGE", "https://api.upstage.ai/v1"), ("CUSTOM", "https://other.example/v1"), ("OLLAMA", "http://x")):
            self.assertFalse(is_reasoning_router(provider, url), provider)
