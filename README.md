# Ferryman

Ferryman is a local-first desktop AI agent platform built with Tauri, React,
and a Python sidecar backend. It packages reusable automations as file-based
Skills and keeps runtime data under the local Ferryman data root instead of a
shared cloud workspace.

## What Ferryman Is For

- Local-first desktop agent workflows
- Skill-based automation distributed as folders and files
- A Python sidecar that handles orchestration, storage, and execution
- A Tauri desktop shell with a React frontend
- BYOK model access for OpenAI-compatible, Anthropic, Gemini, and related providers

## Architecture

- `frontend/`: Tauri shell, React UI, desktop packaging scripts
- `backend/`: FastAPI/WebSocket sidecar, kernel, storage models, toolkits, and Python tests
- `skills/`: built-in Skills with `SKILL.md`, optional `scripts/`, `assets/`, and references

Ferryman uses JSON-RPC 2.0 over WebSocket between the desktop shell and the
local Python process. Local app data is designed to live under `~/.ferryman/`.

## Implementation Details

### Desktop Runtime

The desktop application is packaged with Tauri. The Rust layer starts and
manages the local Python sidecar, generates a random bearer token, reserves a
local port, and passes connection details to the frontend over a Tauri command
bridge.

### Sidecar and Transport

The backend exposes a local WebSocket endpoint and uses JSON-RPC 2.0 for
request and event flow. The frontend connects only to the local sidecar and
does not require a Ferryman cloud control plane for core operation.

### Skills and Execution

Skills are stored as folders with `SKILL.md` plus optional private scripts,
assets, and references. Runtime work is performed against the local Ferryman
workspace, and built-in Skills are bundled into the desktop application for
distribution.

### Data Model

Ferryman stores local state in SQLite and keeps app data under `~/.ferryman/`.
The backend tracks sessions, messages, tasks, schedules, and app configuration
through local models and sidecar-managed persistence.

### Model Access

Ferryman is designed for BYOK usage. Provider credentials are kept local and
the app can route to OpenAI-compatible APIs, Anthropic, Gemini, and related
providers depending on local configuration.

## Local Development

### Prerequisites

- Node.js and npm
- Rust toolchain for Tauri builds
- Conda with a `ferryman` environment for backend development
- macOS is the current primary desktop target

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

Use the Conda environment required by this repository:

```bash
conda activate ferryman
cd backend
python -m pytest
```

When tests need the real local database or other non-sandboxed resources, run
them on the local machine instead of in a restricted sandbox.

## Packaging

### macOS Desktop Build

Ferryman currently ships a macOS desktop packaging flow from the frontend
workspace:

```bash
cd frontend
npm install
npm run dist:mac
```

The packaging flow does the following:

1. Syncs application version metadata
2. Stages the Python backend sidecar into the Tauri bundle
3. Builds the Tauri application bundle
4. Produces a DMG through `frontend/scripts/build_macos_dmg.sh`

### Local Unsigned Build

If Apple signing variables are not provided, the DMG script performs ad-hoc
signing for local smoke testing.

### Signed and Notarized Build

For a signed macOS release, copy
[frontend/.env.release.example](frontend/.env.release.example) to
`frontend/.env.release.local`, then provide:

- `APPLE_SIGNING_IDENTITY`
- `APPLE_NOTARY_ISSUER_ID`
- `APPLE_NOTARY_KEY_ID`
- `APPLE_NOTARY_KEY_PATH`

The notarization private key file should remain outside the repository, such as
under `~/.private_keys/`.

The DMG build script signs the app bundle, verifies packaged resources, submits
the DMG to Apple notarization when configured, staples the accepted notarization,
and copies the final artifacts into `dist/`.

## Security

Do not commit local credentials, API keys, signing certificates, notarization
keys, `.env` files, local database files, or generated release artifacts.

Ferryman includes two layers of secret protection:

1. Local hooks in `.githooks/` for `pre-commit` and `pre-push`
2. A GitHub Actions workflow that scans pushes and pull requests

Enable the local hooks after cloning:

```bash
git config core.hooksPath .githooks
```

The local hooks use `.gitleaks.toml` and `scripts/security/secret_scan.py`.
The CI workflow provides the server-side enforcement surface that local hooks
cannot guarantee by themselves.

For GitHub-hosted repositories, also enable GitHub secret scanning and push
protection in repository settings. GitHub Docs explain that push protection can
block secrets from command-line pushes, GitHub UI commits, file uploads, REST
API writes, and GitHub MCP interactions in supported public repositories:
[About push protection](https://docs.github.com/code-security/secret-scanning/protecting-pushes-with-secret-scanning),
[Push protection for users](https://docs.github.com/en/code-security/secret-scanning/push-protection-for-users),
[Rulesets](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).

## Open Source Governance

- [LICENSE](LICENSE): Apache License 2.0
- [NOTICE](NOTICE): attribution, trademark, and third-party notice summary
- [SECURITY.md](SECURITY.md): how to report vulnerabilities
- [CONTRIBUTING.md](CONTRIBUTING.md): development and contribution guide
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): collaboration expectations

## Trademark

The Apache 2.0 license covers the source code. It does not grant rights to use
the Ferryman name, official logos, application icons,
or signing and distribution identities in a way that suggests an official
release or endorsement.

Forks and commercial distributions are allowed under Apache 2.0, but they
should use their own product names, branding, signing identities, and release
channels unless written permission is granted.

## License

Ferryman source code is licensed under the Apache License, Version 2.0. See
[LICENSE](LICENSE) and [NOTICE](NOTICE).
