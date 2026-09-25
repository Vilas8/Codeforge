import asyncio

from app.services.git import GitService


class StubExecutor:
    calls = []

    @classmethod
    async def run(cls, workspace, command, timeout):
        cls.calls.append(command)
        return {"success": True, "code": 0, "output": "", "error": ""}


def test_commit_quotes_shell_metacharacters(monkeypatch):
    import app.services.git as git_module

    StubExecutor.calls.clear()
    monkeypatch.setattr(git_module, "CommandExecutor", StubExecutor)

    asyncio.run(
        GitService.commit(
            "/tmp/workspace",
            'release $(whoami); echo "unsafe"',
        )
    )

    command = StubExecutor.calls[0]
    assert command.startswith("git add -A && git commit -m ")
    assert "$(whoami)" in command
    assert 'echo "unsafe"' in command
    assert command.count("'") >= 2
