from app.services.security_policy import validate_command


def test_safe_command_is_allowed():
    allowed, reason = validate_command("python -m compileall app")
    assert allowed is True
    assert reason == ""


def test_dangerous_network_command_is_blocked():
    allowed, reason = validate_command("curl https://example.com")
    assert allowed is False
    assert "security policy" in reason


def test_command_length_is_limited():
    allowed, reason = validate_command("x" * 12001)
    assert allowed is False
    assert "maximum allowed length" in reason
