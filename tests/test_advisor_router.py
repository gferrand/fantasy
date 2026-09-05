import json
import unittest
from types import SimpleNamespace

from fantasy_advisor.advisor_router import AdvisorRoute, RoutingError, route_interactive_request


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class AdvisorRouterTests(unittest.TestCase):
    def route(self, output_text, question, **kwargs):
        responses = FakeResponses(output_text)
        client = SimpleNamespace(responses=responses)
        decision = route_interactive_request(
            question,
            api_key="test-key",
            model="router-model",
            reasoning_effort="low",
            client=client,
            **kwargs,
        )
        return decision, responses.calls[0]

    def test_router_uses_capability_reasoning_for_implied_trade_analysis(self):
        decision, call = self.route(
            '{"route":"codex_league","reason":"It needs other-manager rosters and league trade context."}',
            "Could I turn Ajayi into a slightly better midfielder?",
        )
        self.assertEqual(decision.route, AdvisorRoute.CODEX)
        self.assertIn("other managers' rosters", call["instructions"])
        self.assertNotIn("trade(?:", call["instructions"])
        self.assertEqual(json.loads(call["input"])["user_request"], "Could I turn Ajayi into a slightly better midfielder?")

    def test_router_can_keep_a_public_question_on_web_research(self):
        decision, _ = self.route(
            '{"route":"openai_web","reason":"Public club news is sufficient."}',
            "What did the manager say about Balogun's injury?",
        )
        self.assertEqual(decision.route, AdvisorRoute.CHAT)

    def test_router_receives_recent_context_and_request_metadata(self):
        _, call = self.route(
            '{"route":"codex_league","reason":"The attachment and recent conversation require league context."}',
            "What about that option?",
            context_packet="Previous discussion: compare offers involving my roster.",
            waiver_analysis=True,
            has_attachment=True,
        )
        payload = json.loads(call["input"])
        self.assertEqual(payload["recent_conversation"], "Previous discussion: compare offers involving my roster.")
        self.assertTrue(payload["request_metadata"]["is_dedicated_waiver_analysis"])
        self.assertTrue(payload["request_metadata"]["has_user_attachment"])

    def test_invalid_router_response_does_not_silently_choose_a_route(self):
        with self.assertRaisesRegex(RoutingError, "invalid decision"):
            self.route("not json", "Can you help?")


if __name__ == "__main__":
    unittest.main()
