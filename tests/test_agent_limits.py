import asyncio

from app.ai.tools import AgentTools
from app.services.agent import CodeForgeAgent


def test_chat_request_has_bounded_message_and_context_defaults():
    from app.api.chat import ChatRequest

    req = ChatRequest(message="hello")
    assert req.context == {}
    assert req.mode == "build"


def test_agent_prompt_limit():
    agent = object.__new__(CodeForgeAgent)
    agent.messages = []
    agent.mode = "build"
    try:
        asyncio.run(agent.run("x" * 50001))
    except ValueError as exc:
        assert "character limit" in str(exc)
    else:
        raise AssertionError("oversized prompt should be rejected")


def test_tool_read_limit(monkeypatch, tmp_path):
    target = tmp_path / "large.txt"
    target.write_text("x" * 30010, encoding="utf-8")

    monkeypatch.setattr(AgentTools, "workspace_dir", tmp_path, raising=False)
    tool = object.__new__(AgentTools)
    tool.user_id = "u"
    tool.project_id = "p"
    tool.workspace_dir = tmp_path

    monkeypatch.setattr(
        "app.ai.tools.WorkspaceManager.safe_path",
        lambda *args, **kwargs: target,
    )
    result = tool.read_file("large.txt")
    assert "[truncated:" in result
