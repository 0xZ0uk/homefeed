"""Only the Gateway may import yt-dlp (PLAN.md ground rule 1)."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GATEWAY = REPO / "packages" / "core" / "src" / "homefeed_core" / "gateway"
FORBIDDEN = "yt_dlp"


def imports_of(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def python_files() -> list[Path]:
    roots = [REPO / "apps", REPO / "packages"]
    skip = {".venv", "node_modules", "__pycache__"}
    return [
        path
        for root in roots
        for path in root.rglob("*.py")
        if not skip & set(path.relative_to(REPO).parts)
    ]


def test_scan_sees_the_gateway() -> None:
    files = python_files()
    assert GATEWAY / "ytdlp.py" in files
    assert any(FORBIDDEN in imports_of(path) for path in files)


def test_no_module_outside_the_gateway_imports_yt_dlp() -> None:
    offenders = [
        str(path.relative_to(REPO))
        for path in python_files()
        if not path.is_relative_to(GATEWAY)
        and any(m == FORBIDDEN or m.startswith(FORBIDDEN + ".") for m in imports_of(path))
    ]
    assert offenders == []
