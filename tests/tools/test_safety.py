import pytest
from shared.tools.safety import is_destructive


@pytest.mark.parametrize("name,args,expected", [
    ("bash", {"command": "ls -la"}, False),
    ("bash", {"command": "rm -rf /tmp/test"}, True),
    ("bash", {"command": "rmdir /tmp/empty"}, True),
    ("bash", {"command": "kill 1234"}, True),
    ("bash", {"command": "shutdown now"}, True),
    ("bash", {"command": "DROP TABLE users"}, True),
    ("bash", {"command": "DELETE FROM logs"}, True),
    ("bash", {"command": "TRUNCATE sessions"}, True),
    ("bash", {"command": "echo hola"}, False),
    ("bash", {"command": "cat /etc/hosts"}, False),
    ("ssh_exec", {"name": "srv", "command": "rm -rf /var"}, True),
    ("ssh_exec", {"name": "srv", "command": "df -h"}, False),
    ("write_file", {"path": "/etc/passwd", "content": "x"}, False),
    ("read_file", {"path": "/etc/hosts"}, False),
])
def test_is_destructive(name, args, expected):
    assert is_destructive(name, args) == expected
