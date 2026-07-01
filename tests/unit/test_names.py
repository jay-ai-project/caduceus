"""Name validation + container naming (BR-A1/A2 / U8 BR-D1)."""

import pytest

from caduceus.agents.names import container_name, validate_name
from caduceus.common.errors import ProxyError


def test_valid_trimmed():
    assert validate_name("  my-agent.1  ") == "my-agent.1"


def test_container_prefix():
    assert container_name("x") == "cad-x"
    assert container_name("my-agent.1") == "cad-my-agent.1"


@pytest.mark.parametrize("bad", ["", "   ", "a b", "a/b", "in@valid", "x" * 51,
                                 "-lead", ".lead", "has+plus"])
def test_invalid_rejected(bad):
    with pytest.raises(ProxyError):
        validate_name(bad)
