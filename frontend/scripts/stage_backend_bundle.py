from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS_SRC = ROOT / "skills"
GEN_ROOT = ROOT / "frontend" / "src-tauri" / "gen"
BACKEND_BUILD_ROOT = GEN_ROOT / "build"
BACKEND_DIST_ROOT = BACKEND_BUILD_ROOT / "dist"
BACKEND_WORK_ROOT = BACKEND_BUILD_ROOT / "work"
BACKEND_CACHE_ROOT = BACKEND_BUILD_ROOT / "cache"
BACKEND_DST = GEN_ROOT / "backend-sidecar"
SKILLS_DST = GEN_ROOT / "skills"
FORBIDDEN_PROMPT_FILES = {"GEMINI.md", "AGENT.md", "CLAUDE.md"}
PYINSTALLER_SPEC = ROOT / "backend" / "ferryman_backend.spec"


def candidate_backend_pythons() -> list[Path]:
    candidates: list[Path] = []
    env_override = os.environ.get("FERRYMAN_BACKEND_PYTHON")
    if env_override:
        candidates.append(Path(env_override).expanduser())

    home = Path.home()
    candidates.extend(
        [
            home / "miniconda3" / "envs" / "ferryman" / "bin" / "python",
            home / "anaconda3" / "envs" / "ferryman" / "bin" / "python",
        ]
    )

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidates.append(Path(conda_prefix) / "bin" / "python")

    candidates.append(Path(sys.executable))
    return candidates


def resolve_backend_python() -> Path:
    for candidate in candidate_backend_pythons():
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "Could not locate a Python interpreter for the ferryman backend build. "
        "Set FERRYMAN_BACKEND_PYTHON or activate the ferryman environment first."
    )


def reset_destination() -> None:
    if GEN_ROOT.exists():
        shutil.rmtree(GEN_ROOT)
    BACKEND_DST.mkdir(parents=True, exist_ok=True)
    SKILLS_DST.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".DS_Store",
            ".pytest_cache",
            ".logfire",
            ".env",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            ".git",
        ),
    )


def build_backend_sidecar() -> None:
    python_executable = resolve_backend_python()
    build_env = os.environ.copy()
    build_env["PYINSTALLER_CONFIG_DIR"] = str(BACKEND_CACHE_ROOT)
    cmd = [
        str(python_executable),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(BACKEND_DIST_ROOT),
        "--workpath",
        str(BACKEND_WORK_ROOT),
        str(PYINSTALLER_SPEC),
    ]
    try:
        subprocess.run(cmd, check=True, cwd=ROOT, env=build_env)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "PyInstaller build failed. Install backend build requirements with "
            f"`{python_executable} -m pip install -r backend/requirements-build.txt`."
        ) from exc

    built_dir = BACKEND_DIST_ROOT / "ferryman"
    if not built_dir.exists():
        raise RuntimeError(f"Expected built backend sidecar at {built_dir}")
    shutil.copytree(built_dir, BACKEND_DST, dirs_exist_ok=True)


def copy_skills() -> None:
    if SKILLS_SRC.exists():
        copy_tree(SKILLS_SRC, SKILLS_DST)


def ensure_no_forbidden_files(root: Path) -> None:
    forbidden = [path for path in root.rglob("*") if path.name in FORBIDDEN_PROMPT_FILES]
    if forbidden:
        names = ", ".join(str(path) for path in forbidden)
        raise RuntimeError(f"Forbidden project prompt files found in staged bundle: {names}")


def main() -> None:
    reset_destination()
    build_backend_sidecar()
    copy_skills()
    ensure_no_forbidden_files(GEN_ROOT)


if __name__ == "__main__":
    main()
