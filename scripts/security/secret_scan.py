#!/usr/bin/env python3
"""Secret scanner used by Ferryman's local git hooks."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath


ZERO_SHA = "0" * 40
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    source: str
    line: int
    rule: str
    detail: str


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    detail: str


RULES = [
    Rule("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}"), "Google/Gemini API key"),
    Rule("openai-api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "OpenAI-compatible API key"),
    Rule(
        "github-token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
        "GitHub token",
    ),
    Rule("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    Rule("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Private key block"),
    Rule(
        "apple-notary-env",
        re.compile(
            r"\b(?:APPLE_SIGNING_IDENTITY|APPLE_NOTARY_ISSUER_ID|APPLE_NOTARY_KEY_ID|APPLE_NOTARY_KEY_PATH)"
            r"\s*=\s*['\"][^'\"]+['\"]",
            re.IGNORECASE,
        ),
        "Apple signing/notarization value",
    ),
    Rule("apple-authkey", re.compile(r"AuthKey_[A-Z0-9]{10}\.p8"), "Apple notarization private key file"),
]


ALLOWED_PATHS = {
    "frontend/.env.release.example",
}


TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".lock",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def run_git(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def is_allowed_example(path: str) -> bool:
    name = PurePosixPath(path).name
    return path in ALLOWED_PATHS or name == ".env.example" or name.endswith(".example")


def is_env_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name == ".env" or name.startswith(".env.")


def should_scan_text(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    if is_env_file(path):
        return True
    return suffix in TEXT_EXTENSIONS


def scan_path_policy(path: str, source: str) -> list[Finding]:
    if is_env_file(path) and not is_allowed_example(path):
        return [Finding(source, 1, "env-file", "Do not commit local .env files")]
    if path.endswith((".p8", ".pem", ".key", ".mobileprovision")):
        return [Finding(source, 1, "signing-file", "Do not commit signing keys or provisioning files")]
    return []


def scan_text(text: str, source: str, *, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if is_allowed_example(path) and "=''" in stripped:
            continue
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append(Finding(source, index, rule.name, rule.detail))
    return findings


def decode_blob(data: bytes) -> str | None:
    if b"\0" in data[:4096] or len(data) > MAX_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def git_blob(ref: str, path: str) -> bytes | None:
    spec = f":{path}" if ref == ":" else f"{ref}:{path}"
    proc = subprocess.run(["git", "show", spec], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        return None
    return proc.stdout


def staged_paths() -> list[str]:
    proc = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"])
    return [p for p in proc.stdout.split("\0") if p]


def changed_paths(commit: str) -> list[str]:
    proc = run_git(["diff-tree", "--no-commit-id", "--name-only", "--diff-filter=ACMR", "-r", "-z", commit])
    return [p for p in proc.stdout.split("\0") if p]


def scan_ref_path(ref: str, path: str, source: str) -> list[Finding]:
    findings = scan_path_policy(path, source)
    if not should_scan_text(path):
        return findings
    blob = git_blob(ref, path)
    if blob is None:
        return findings
    text = decode_blob(blob)
    if text is None:
        return findings
    return findings + scan_text(text, source, path=path)


def scan_staged() -> list[Finding]:
    findings: list[Finding] = []
    for path in staged_paths():
        findings.extend(scan_ref_path(":", path, f"staged:{path}"))
    return findings


def commits_for_push(local_sha: str, remote_sha: str) -> list[str]:
    if not local_sha or local_sha == ZERO_SHA:
        return []
    if remote_sha and remote_sha != ZERO_SHA:
        spec = f"{remote_sha}..{local_sha}"
        proc = run_git(["rev-list", spec], check=False)
        if proc.returncode == 0:
            return [line for line in proc.stdout.splitlines() if line]
    proc = run_git(["rev-list", local_sha, "--not", "--remotes"], check=False)
    commits = [line for line in proc.stdout.splitlines() if line]
    return commits or [local_sha]


def scan_pre_push(stdin: str) -> list[Finding]:
    findings: list[Finding] = []
    for raw_line in stdin.splitlines():
        parts = raw_line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        for commit in commits_for_push(local_sha, remote_sha):
            for path in changed_paths(commit):
                findings.extend(scan_ref_path(commit, path, f"{commit[:12]}:{path}"))
    return findings


def tracked_paths() -> list[str]:
    proc = run_git(["ls-files", "-z"])
    return [p for p in proc.stdout.split("\0") if p]


def scan_repo_tree() -> list[Finding]:
    findings: list[Finding] = []
    for path in tracked_paths():
        findings.extend(scan_ref_path("HEAD", path, f"repo:{path}"))
    return findings


def print_findings(findings: list[Finding]) -> None:
    if not findings:
        return
    print("Secret scan blocked this git operation:", file=sys.stderr)
    for finding in findings:
        print(f"- {finding.source}:{finding.line} [{finding.rule}] {finding.detail}", file=sys.stderr)
    print("\nRemove the secret, rotate it if it was real, and commit an example placeholder instead.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--pre-push", action="store_true")
    group.add_argument("--repo", action="store_true")
    args = parser.parse_args()

    if args.staged:
        findings = scan_staged()
    elif args.pre_push:
        findings = scan_pre_push(sys.stdin.read())
    else:
        findings = scan_repo_tree()
    print_findings(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
