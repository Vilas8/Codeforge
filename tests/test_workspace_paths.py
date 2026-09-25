import sys
import types

# WorkspaceManager imports storage, which imports the database client.
# Stub that client so path validation tests remain fully local and deterministic.
fake_client = types.ModuleType("app.database.client")
fake_client.supabase = object()
sys.modules.setdefault("app.database.client", fake_client)

from app.projects.workspace import WorkspaceManager


def test_normalize_workspace_path():
    assert WorkspaceManager.normalize_relative_path("src\\main.py") == "src/main.py"
    assert WorkspaceManager.normalize_relative_path("/src/main.py/") == "src/main.py"


def test_rejects_traversal_and_hidden_paths():
    for path in ("../secret", "src/../secret", ".env", "src/.hidden", "/"):
        try:
            WorkspaceManager.normalize_relative_path(path)
        except ValueError:
            continue
        raise AssertionError(f"path should be rejected: {path}")


def test_allows_empty_only_when_requested():
    assert WorkspaceManager.normalize_relative_path("", allow_empty=True) == ""
    try:
        WorkspaceManager.normalize_relative_path("", allow_empty=False)
    except ValueError:
        pass
    else:
        raise AssertionError("empty path should be rejected")
