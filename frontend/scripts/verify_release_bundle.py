from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
BUNDLE_SMOKE_SKILL_NAME = "bundle-smoke-skill"


def required_paths(app_path: Path) -> list[Path]:
    resources = app_path / "Contents" / "Resources" / "gen"
    return [
        resources / "backend-sidecar" / "ferryman",
        resources / "backend-sidecar" / "_internal" / "playwright_stealth" / "js" / "generate.magic.arrays.js",
        resources / "backend-sidecar" / "_internal" / "trafilatura" / "settings.cfg",
        resources / "backend-sidecar" / "_internal" / "justext" / "stoplists",
        resources / "skills",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the packaged Ferryman macOS bundle.")
    parser.add_argument(
        "--app-path",
        default=str(ROOT / "src-tauri" / "target" / "release" / "bundle" / "macos" / "Ferryman.app"),
        help="Path to the built Ferryman.app bundle.",
    )
    return parser.parse_args()


def app_executable(app_path: Path) -> Path:
    macos_dir = app_path / "Contents" / "MacOS"
    executables = [path for path in macos_dir.iterdir() if path.is_file() and os.access(path, os.X_OK)]
    if not executables:
        raise RuntimeError(f"No executable found in {macos_dir}")
    return executables[0]


def ensure_packaged_skills_clean(skills_dir: Path) -> None:
    leaked_skill_dir = skills_dir / BUNDLE_SMOKE_SKILL_NAME
    if leaked_skill_dir.exists():
        raise RuntimeError(
            f"Packaged skills unexpectedly contain internal smoke skill: {leaked_skill_dir}"
        )


def write_bundle_smoke_skill(skills_dir: Path) -> None:
    skill_dir = skills_dir / BUNDLE_SMOKE_SKILL_NAME
    assets_dir = skill_dir / "assets"
    references_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    assets_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {BUNDLE_SMOKE_SKILL_NAME}\n"
            "description: Internal release bundle verification skill.\n"
            "version: 1.0.0\n"
            "author: Ferryman\n"
            "created: 2026-04-15\n"
            "updated: 2026-04-15\n"
            "---\n\n"
            "# Internal Bundle Smoke Skill\n"
        ),
        encoding="utf-8",
    )
    (assets_dir / "sample.txt").write_text(
        "Ferryman bundled skill asset check.\n",
        encoding="utf-8",
    )
    (references_dir / "sample.md").write_text(
        "# Bundle Smoke Reference\nFerryman bundled skill reference check.\n",
        encoding="utf-8",
    )
    (scripts_dir / "verify_bundle_resources.py").write_text(
        (
            "from __future__ import annotations\n\n"
            "import json\n"
            "from pathlib import Path\n\n"
            "skill_dir = Path(__file__).resolve().parents[1]\n"
            "asset = (skill_dir / 'assets' / 'sample.txt').read_text(encoding='utf-8').strip()\n"
            "reference = (skill_dir / 'references' / 'sample.md').read_text(encoding='utf-8').strip()\n"
            "print(json.dumps({'asset': asset, 'reference': reference}, ensure_ascii=False))\n"
        ),
        encoding="utf-8",
    )


def build_smoke_skills_dir(packaged_skills_dir: Path, temp_root: Path) -> Path:
    ensure_packaged_skills_clean(packaged_skills_dir)

    staged_skills_dir = temp_root / "skills"
    shutil.copytree(packaged_skills_dir, staged_skills_dir, dirs_exist_ok=True)
    write_bundle_smoke_skill(staged_skills_dir)
    return staged_skills_dir


def run_frontend_ui_smoke(app_path: Path) -> None:
    executable = app_executable(app_path)
    with tempfile.TemporaryDirectory(prefix="ferryman-frontend-smoke-") as temp_root:
        marker_path = Path(temp_root) / "frontend-smoke.json"
        env = os.environ.copy()
        env["FERRYMAN_FRONTEND_SMOKE_MARKER"] = str(marker_path)
        env["FERRYMAN_FRONTEND_SMOKE_AUTO_EXIT"] = "1"
        env.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")

        process = subprocess.Popen(
            [str(executable)],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 45
            while time.time() < deadline:
                if marker_path.exists():
                    payload = json.loads(marker_path.read_text(encoding="utf-8"))
                    if payload.get("status") == "backend_connected":
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                            process.wait(timeout=10)
                        if process.returncode not in (0, None):
                            raise RuntimeError(f"Frontend UI smoke app exited with code {process.returncode}")
                        return

                if process.poll() is not None and not marker_path.exists():
                    raise RuntimeError(f"Frontend UI smoke app exited before reporting backend connection. Exit code: {process.returncode}")

                time.sleep(0.25)

            raise RuntimeError("Frontend UI smoke timed out waiting for backend_connected marker.")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def main() -> int:
    args = parse_args()
    app_path = Path(args.app_path).resolve()
    if not app_path.exists():
        raise RuntimeError(f"App bundle not found at {app_path}")

    missing = [str(path) for path in required_paths(app_path) if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing required packaged resources: {missing}")

    stoplists_dir = app_path / "Contents" / "Resources" / "gen" / "backend-sidecar" / "_internal" / "justext" / "stoplists"
    if not any(stoplists_dir.glob("*.txt")):
        raise RuntimeError(f"Packaged jusText stoplists directory is empty: {stoplists_dir}")

    sidecar = app_path / "Contents" / "Resources" / "gen" / "backend-sidecar" / "ferryman"
    packaged_skills_dir = app_path / "Contents" / "Resources" / "gen" / "skills"

    with tempfile.TemporaryDirectory(prefix="ferryman-release-smoke-") as temp_root:
        staged_skills_dir = build_smoke_skills_dir(packaged_skills_dir, Path(temp_root))
        env = os.environ.copy()
        env["FERRYMAN_ROOT_DIR"] = temp_root
        env["FERRYMAN_BUNDLED_SKILLS_DIR"] = str(staged_skills_dir)
        env["PYDANTIC_DISABLE_PLUGINS"] = "1"
        result = subprocess.run(
            [str(sidecar), "--smoke-test-bundle"],
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    if result.returncode != 0:
        raise RuntimeError(
            "Bundled sidecar smoke test failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError(f"Could not parse bundled smoke test output: {result.stdout}") from exc

    run_frontend_ui_smoke(app_path)
    report["checks"].append({"name": "frontend_ui_backend"})

    dist_dir = PROJECT_ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    shutil.copytree(app_path, dist_dir / app_path.name, dirs_exist_ok=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
