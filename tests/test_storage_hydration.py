from pathlib import Path

import pytest

from app.projects.workspace import WorkspaceManager


def test_storage_path_is_rejected_during_hydration(monkeypatch, tmp_path):
    workspace = tmp_path / "workspaces" / "u" / "p"
    monkeypatch.setattr("app.projects.workspace.WORKSPACE_BASE", tmp_path / "workspaces")
    workspace.mkdir(parents=True)

    with pytest.raises(ValueError):
        WorkspaceManager.safe_path("u", "p", "../outside.txt")


def test_hidden_storage_path_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("app.projects.workspace.WORKSPACE_BASE", tmp_path / "workspaces")
    (tmp_path / "workspaces" / "u" / "p").mkdir(parents=True)

    with pytest.raises(ValueError):
        WorkspaceManager.safe_path("u", "p", ".env")


def test_workspace_safe_path_resolves_normalized_storage_names(monkeypatch, tmp_path):
    monkeypatch.setattr("app.projects.workspace.WORKSPACE_BASE", tmp_path / "workspaces")
    (tmp_path / "workspaces" / "u" / "p").mkdir(parents=True)

    target = WorkspaceManager.safe_path("u", "p", "src/main.py")
    assert target == tmp_path / "workspaces" / "u" / "p" / "src" / "main.py"
