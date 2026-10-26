"""노트북 맞춤설정을 채팅 요청에 붙인다(F3-01)."""
from __future__ import annotations

import unittest
from dataclasses import dataclass, replace

from daon2_user_api.question_answering_service import QuestionAnsweringService


@dataclass(frozen=True)
class _Prepared:
    provider_payload: dict


@dataclass(frozen=True)
class _Ctx:
    notebook_id: str | None = "nb-1"


def _service(provider):
    service = QuestionAnsweringService.__new__(QuestionAnsweringService)
    service._customization_provider = provider
    return service


def _prepared():
    return _Prepared({"model": "m", "messages": [{"role": "system", "content": "기본 지시"}, {"role": "user", "content": "질문"}]})


class ChatCustomizationTests(unittest.TestCase):
    def test_instruction_is_appended_to_first_system_message_only(self):
        out = _service(lambda ctx: " 존댓말로 답해 ")._with_customization(_Ctx(), _prepared())
        messages = out.provider_payload["messages"]
        self.assertTrue(messages[0]["content"].startswith("기본 지시\n\n[노트북 맞춤설정 — 사용자 지시]\n존댓말로 답해"))
        self.assertEqual(messages[1], {"role": "user", "content": "질문"})

    def test_payload_is_unchanged_without_instruction_notebook_or_on_failure(self):
        base = _prepared()
        self.assertIs(_service(lambda ctx: "  ")._with_customization(_Ctx(), base), base)
        self.assertIs(_service(None)._with_customization(_Ctx(), base), base)
        self.assertIs(_service(lambda ctx: "x")._with_customization(_Ctx(None), base), base)

        def boom(ctx):
            raise RuntimeError("db down")
        self.assertIs(_service(boom)._with_customization(_Ctx(), base), base)


if __name__ == "__main__":
    unittest.main()
