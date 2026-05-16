import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "validate_plugin"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_plugin.py"


def run_validator(plugin_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(plugin_root)],
        capture_output=True,
        text=True,
    )


def test_good_fixture_passes():
    result = run_validator(FIXTURES / "good")
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "✓ plugin.json" in result.stdout
    assert "✓ skills/sample/SKILL.md" in result.stdout
    assert "✓ agents/coding.py" in result.stdout
