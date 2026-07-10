from __future__ import annotations

from pathlib import Path

from sforge.author.workspace import count_repo_loc, temp_workspace


def _write_lines(path: Path, n: int) -> None:
    path.write_text("\n".join(f"line{i}" for i in range(n)) + "\n")


def test_count_repo_loc_go_ignores_non_go(tmp_path: Path) -> None:
    _write_lines(tmp_path / "a.go", 5)
    _write_lines(tmp_path / "b.go", 10)
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_lines(sub / "c.go", 15)
    (tmp_path / "notes.txt").write_text("ignored\ntext\n")
    assert count_repo_loc(tmp_path, "go") == 30


def test_count_repo_loc_skips_vendor(tmp_path: Path) -> None:
    _write_lines(tmp_path / "main.go", 3)
    vendor = tmp_path / "vendor" / "dep"
    vendor.mkdir(parents=True)
    _write_lines(vendor / "dep.go", 100)
    assert count_repo_loc(tmp_path, "go") == 3


def test_count_repo_loc_skips_node_modules(tmp_path: Path) -> None:
    _write_lines(tmp_path / "app.ts", 4)
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    _write_lines(nm / "index.ts", 50)
    assert count_repo_loc(tmp_path, "typescript") == 4


def test_count_repo_loc_typescript_tsx(tmp_path: Path) -> None:
    _write_lines(tmp_path / "a.ts", 2)
    _write_lines(tmp_path / "b.tsx", 3)
    assert count_repo_loc(tmp_path, "typescript") == 5


def test_temp_workspace_yields_path_and_cleans_up() -> None:
    with temp_workspace() as p:
        assert isinstance(p, Path)
        assert p.exists()
        assert p.is_dir()
        assert p.name.startswith("sforge-author-")
        captured = p
    assert not captured.exists()
