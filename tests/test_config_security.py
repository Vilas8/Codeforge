import os

import pytest

from app.core.config import Settings


def make_settings(**overrides):
    values = {
        "supabase_url": "https://example.supabase.co",
        "supabase_anon_key": "anon",
        "supabase_service_role_key": "service",
        **overrides,
    }
    return Settings(**values)


def test_production_requires_cors_origins_and_trusted_hosts():
    with pytest.raises(ValueError):
        make_settings(app_env="production", cors_origins="", trusted_hosts="")


def test_production_rejects_wildcard_security_settings():
    with pytest.raises(ValueError):
        make_settings(
            app_env="production",
            cors_origins="*",
            trusted_hosts="codeforge.example.com",
        )
    with pytest.raises(ValueError):
        make_settings(
            app_env="production",
            cors_origins="https://codeforge.example.com",
            trusted_hosts="*",
        )


def test_production_accepts_explicit_security_settings():
    settings = make_settings(
        app_env="production",
        cors_origins="https://codeforge.example.com",
        trusted_hosts="codeforge.example.com",
    )
    assert settings.request_max_body_mb == 10


def test_request_body_limit_has_safe_bounds():
    with pytest.raises(ValueError):
        make_settings(request_max_body_mb=0)
    with pytest.raises(ValueError):
        make_settings(request_max_body_mb=101)
