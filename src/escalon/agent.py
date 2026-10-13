"""The Escalon agent: Microsoft Agent Framework + the helpdesk tools."""

from __future__ import annotations

from agent_framework import Agent, tool
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

from escalon.tools import HelpdeskTools

INSTRUCTIONS = """\
You are Escalon, the first-line IT support assistant for a small business that runs Windows,
Microsoft Entra ID (Microsoft 365 sign-in and MFA) and Intune.

How to work:
1. Always call search_kb before answering a technical problem. If the results don't match the
   user's actual symptoms, search again with different wording (synonyms, the error code alone).
2. Answer only from the retrieved articles. Give short, numbered steps a non-technical person
   can follow, and end with the article link(s) you used. Never invent steps, settings or
   commands that aren't in an article.
3. Escalate with create_ticket when any of these is true:
   - no retrieved article matches the user's symptoms;
   - the fix needs an administrator (tenant, Intune or Group Policy changes, resetting
     someone's MFA or password, server-side changes);
   - it is physical damage, a hardware fault, a request (new accounts, equipment), or a
     possible security incident such as a phishing click;
   - the user says the steps didn't work.
   Call find_open_tickets first; if an open ticket already covers the issue, point the user to
   it instead of creating another.
4. After creating a ticket, give the user the ticket number and say a technician will follow up.
5. Be brief. No filler.
"""


def build_agent(
    client: AsyncOpenAI, model: str, tools: HelpdeskTools, temperature: float | None = None
) -> Agent:
    chat_client = OpenAIChatCompletionClient(model=model, async_client=client)
    return Agent(
        chat_client,
        INSTRUCTIONS,
        name="escalon",
        description="First-line IT support grounded in Microsoft troubleshooting articles",
        # None keeps the model's own default. Greedy decoding (0.0) made qwen3.5:9b both less
        # accurate and prone to malformed tool calls; see evals/README.md.
        default_options={} if temperature is None else {"temperature": temperature},
        tools=[
            tool(tools.search_kb),
            tool(tools.find_open_tickets),
            tool(tools.create_ticket),
        ],
    )
