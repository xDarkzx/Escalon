"""Runs the real Agent Framework tool loop through /api/chat against a scripted model."""

import json
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion
from starlette.testclient import TestClient

from escalon.server import create_app
from tests.test_server import FakeIndex, FakeTickets, settings

ARTICLE_URL = "https://learn.microsoft.com/en-us/troubleshoot/windows-client/printing/a"


def completion(message: dict) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "c",
            "object": "chat.completion",
            "created": 0,
            "model": "scripted",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}],
        }
    )


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


class ScriptedModel:
    """Plays back a fixed sequence of model turns and records what the agent sent."""

    base_url = "scripted://model"

    def __init__(self, turns: list[dict]) -> None:
        self._turns = iter(turns)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: object) -> ChatCompletion:
        self.requests.append(kwargs)
        return completion(next(self._turns))


@pytest.fixture
def run_chat():
    def run(turns: list[dict], message: str):
        model = ScriptedModel(turns)
        tickets = FakeTickets()
        app = create_app(
            settings(auth_mode="disabled", dev_user_email="dev@contoso.test"),
            index=FakeIndex(),
            tickets=tickets,
            llm=model,  # type: ignore[arg-type]
        )
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": message})
        return response, model, tickets

    return run


def test_agent_searches_then_answers_with_citation(run_chat):
    response, model, tickets = run_chat(
        [
            tool_call("search_kb", {"query": "printer 0x0000052e"}),
            {"content": f"1. Open Credential Manager.\n\n{ARTICLE_URL}"},
        ],
        "printer says 0x0000052e",
    )

    assert response.status_code == 200
    body = response.json()
    assert ARTICLE_URL in body["reply"]
    assert body["tickets_created"] == []
    assert "temperature" not in model.requests[0]  # model default unless configured
    # The search result was fed back to the model as a tool message.
    tool_messages = [m for m in model.requests[1]["messages"] if m["role"] == "tool"]
    assert "Network printer error" in json.dumps(tool_messages)
    assert tickets.created == []


def test_agent_escalation_files_ticket_as_session_user(run_chat):
    response, _, tickets = run_chat(
        [
            tool_call("search_kb", {"query": "coffee keyboard"}),
            tool_call("find_open_tickets", {}),
            tool_call(
                "create_ticket",
                {
                    "title": "Liquid damage",
                    "symptoms": "keys dead",
                    "steps_tried": "none",
                    "relevant_article_urls": [],
                },
            ),
            {"content": "I've logged ticket #31001."},
        ],
        "spilled coffee on my keyboard",
    )

    assert response.json()["tickets_created"] == ["31001"]
    assert tickets.created[0][0] == "dev@contoso.test"


def test_invented_ticket_number_never_reaches_the_user(run_chat):
    response, _, tickets = run_chat(
        [{"content": "I've opened a ticket for you: **#24576**"}],
        "please reset my password",
    )

    body = response.json()
    assert "24576" not in body["reply"]
    assert body["tickets_created"] == ["31001"]
    assert tickets.created[0][2].startswith("Reported by the user via Escalon")
