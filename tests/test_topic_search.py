import json
import re
import unittest

from app.webhook import app
from app.db import SessionState, User, get_session, init_db
from app.core import PAGE_SIZE, _topic_tokens_from_text, generar_respuesta


TEST_NUMBER = "1111"


def _ensure_test_user():
    with get_session() as session:
        user = session.query(User).filter_by(wa_number=TEST_NUMBER).first()
        if not user:
            user = User(wa_number=TEST_NUMBER, consent_accepted=True)
            session.add(user)
            session.flush()
            session.add(SessionState(user_id=user.id, state="COMPLETED", data={}))
        else:
            user.consent_accepted = True
            if user.session_state:
                user.session_state.state = "COMPLETED"
            else:
                session.add(SessionState(user=user, state="COMPLETED", data={}))


class TopicSearchWebhookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _ensure_test_user()
        app.testing = True

    def setUp(self):
        self.client = app.test_client()

    def _post_text(self, text: str):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": TEST_NUMBER,
                                        "id": f"msg-{text}",
                                        "type": "text",
                                        "text": {"body": text},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        return self.client.post("/webhook", json=payload)

    def test_topic_queries_do_not_crash(self):
        for query in ["tecnologos", "programas sobre sistemas", "mecánica de motos"]:
            resp = self._post_text(query)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_data(as_text=True), "ok")

    def test_stopwords_keep_sistemas(self):
        tokens = _topic_tokens_from_text("programas sobre sistemas")
        self.assertIn("sistemas", tokens)

    def test_mixed_query_respects_explicit_city(self):
        reply = generar_respuesta("programación en guapi")
        self.assertNotIn("Popayán", reply)
        self.assertIn("Guapi", reply)

        reply_no_matches = generar_respuesta("astronomía en guapi")
        self.assertIn("No encontré programas en Guapi", reply_no_matches)

    def test_location_only_query_routes_by_city(self):
        reply = generar_respuesta("programas en popayan")
        self.assertIn("popayan", reply.lower())
        self.assertNotIn("coincidan con popayan", reply.lower())

    def test_level_location_header(self):
        reply = generar_respuesta("tecnologos en popayan")
        self.assertIn("tecnologos en *popayan*", reply.lower())

    def test_page_size_is_five(self):
        replies = [
            generar_respuesta("programas sobre sistemas"),
            generar_respuesta("programas en popayan"),
            generar_respuesta("sistemas en popayan"),
        ]

        for reply in replies:
            item_numbers = [
                int(match.group(1))
                for match in re.finditer(r"^\s*(\d+)\)", reply, flags=re.MULTILINE)
            ]
            self.assertTrue(item_numbers)
            self.assertLessEqual(max(item_numbers), PAGE_SIZE)


if __name__ == "__main__":
    unittest.main()
