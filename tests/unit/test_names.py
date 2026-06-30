"""Name validation + sandbox naming (BR-A1/A2)."""

import pytest

from caduceus.agents.names import sandbox_name, validate_name
from caduceus.common.errors import ProxyError


def test_valid_trimmed():
    assert validate_name("  my-agent.1  ") == "my-agent.1"


def test_sandbox_prefix():
    assert sandbox_name("x") == "cad-x"
    assert sandbox_name("my-agent.1") == "cad-my-agent.1"


@pytest.mark.parametrize("bad", ["", "   ", "a b", "a/b", "in@valid", "x" * 51])
def test_invalid_rejected(bad):
    with pytest.raises(ProxyError):
        validate_name(bad)
