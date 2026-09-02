import unittest

from fantasy_advisor.advisor_router import AdvisorRoute, route_interactive_request


class AdvisorRouterTests(unittest.TestCase):
    def test_current_deal_question_uses_lightweight_web_research(self):
        decision = route_interactive_request("What happened to the Balogun Everton deal?")
        self.assertEqual(decision.route, AdvisorRoute.CHAT)
        self.assertIn("web research", decision.reason)

    def test_team_fit_question_uses_codex_with_league_data(self):
        decision = route_interactive_request("Is Balogun a good fit for my team?")
        self.assertEqual(decision.route, AdvisorRoute.CODEX)
        self.assertIn("Sleeper", decision.reason)

    def test_waivers_and_dedicated_waiver_command_stay_on_codex(self):
        self.assertEqual(
            route_interactive_request("Who are the best free agents on waivers?").route,
            AdvisorRoute.CODEX,
        )
        self.assertEqual(
            route_interactive_request("Anything", waiver_analysis=True).route,
            AdvisorRoute.CODEX,
        )

    def test_attachment_analysis_stays_on_codex(self):
        self.assertEqual(
            route_interactive_request("Summarize this", has_attachment=True).route,
            AdvisorRoute.CODEX,
        )

    def test_general_follow_up_uses_same_context_capable_web_path(self):
        self.assertEqual(
            route_interactive_request("What did I just ask you?").route,
            AdvisorRoute.CHAT,
        )

    def test_public_player_facts_do_not_need_the_private_league_path(self):
        self.assertEqual(
            route_interactive_request("Is Balogun injured or likely to start this weekend?").route,
            AdvisorRoute.CHAT,
        )
        self.assertEqual(
            route_interactive_request("Who does Balogun face in the next fixture?").route,
            AdvisorRoute.CHAT,
        )

    def test_applying_public_facts_to_the_owner_roster_uses_codex(self):
        self.assertEqual(
            route_interactive_request("Which injured starter should I replace in my lineup?").route,
            AdvisorRoute.CODEX,
        )


if __name__ == "__main__":
    unittest.main()
