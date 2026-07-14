import json
import unittest

from dola_client import DolaClient


class VideoProtocolCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.client = DolaClient("sessionid=test-session; s_v_web_id=test-fp")

    def test_video_body_uses_nested_current_ability(self):
        body = self.client._build_video_body(
            "固定镜头中的蓝色圆形",
            ratio="1:1",
            duration=5,
        )

        self.assertEqual(17, body["chat_ability"]["ability_type"])
        nested = json.loads(body["chat_ability"]["ability_param"])
        self.assertEqual(50, nested["ability_type"])
        self.assertEqual(
            {"ratio": "1:1", "duration": 5},
            nested["ability_param"],
        )
        self.assertNotIn("seedance_v2.0", body["chat_ability"]["ability_param"])

        input_skill = json.loads(body["ext"]["input_skill"])
        self.assertEqual({"skill_id": "17", "skill_type": 17}, input_skill)

    def test_extracts_video_conversation_id_from_supported_ack_shapes(self):
        cases = [
            [("SSE_ACK", {"ack_client_meta": {"conversation_id": "conv-direct"}})],
            [("SSE_ACK", {"data": {"ack_client_meta": {"conversation_id": "conv-wrapped"}}})],
            [("SSE_ACK", {"conversation_id": "conv-top-level"})],
        ]

        self.assertEqual(
            ["conv-direct", "conv-wrapped", "conv-top-level"],
            [self.client._extract_video_conversation_id(events) for events in cases],
        )

    def test_sse_summary_contains_structure_not_values(self):
        events = [
            (
                "SSE_ACK",
                {
                    "ack_client_meta": {"conversation_id": "secret-conversation"},
                    "credential": "secret-cookie-value",
                },
            )
        ]

        summary = self.client._summarize_sse_events(events)

        self.assertIn("SSE_ACK", summary)
        self.assertIn("ack_client_meta", summary)
        self.assertIn("credential", summary)
        self.assertNotIn("secret-conversation", summary)
        self.assertNotIn("secret-cookie-value", summary)


if __name__ == "__main__":
    unittest.main()
