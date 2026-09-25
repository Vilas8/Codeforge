from pathlib import Path

import pytest

from app.projects.workspace import WorkspaceManager


def test_safe_path_rejects_workspace_escape():
    with pytest.raises(ValueError):
        WorkspaceManager.safe_path("user", "project", "../outside.txt")


def test_safe_path_rejects_symlink_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.projects.workspace.WORKSPACE_BASE",
        tmp_path / "workspaces",
    )
    workspace = tmp_path / "workspaces" / "user" / "project"
    workspace.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        WorkspaceManager.safe_path("user", "project", "linked/secret.txt")


def test_safe_path_allows_normal_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.projects.workspace.WORKSPACE_BASE",
        tmp_path / "workspaces",
    )
    workspace = tmp_path / "workspaces" / "user" / "project"
    workspace.mkdir(parents=True)
    target = WorkspaceManager.safe_path("user", "project", "src/main.py")
    assert target == workspace / "src" / "main.py"
