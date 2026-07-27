import pytest

from deploy.soarctl_lib.prompts import _valid_origin, prompt_cors_origins


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://x", True),
        ("https://x", True),
        ("https://soar.example.com", True),
        ("", False),
        ("x", False),
        ("ftp://x", False),
        ("localhost:3000", False),
    ],
)
def test_valid_origin(url, expected):
    assert _valid_origin(url) is expected


def test_prompt_cors_origins_accepts_valid_input_first_try():
    answers = iter(["https://soar.example.com"])
    result = prompt_cors_origins(input_fn=lambda _prompt: next(answers))
    assert result == ["https://soar.example.com"]


def test_prompt_cors_origins_parses_comma_separated_list():
    answers = iter(["https://a.example.com, https://b.example.com"])
    result = prompt_cors_origins(input_fn=lambda _prompt: next(answers))
    assert result == ["https://a.example.com", "https://b.example.com"]


def test_prompt_cors_origins_reprompts_on_invalid_input():
    calls = []
    answers = iter(["not-a-url", "", "https://soar.example.com"])

    def fake_input(prompt):
        calls.append(prompt)
        return next(answers)

    result = prompt_cors_origins(input_fn=fake_input)

    assert result == ["https://soar.example.com"]
    assert len(calls) == 3
