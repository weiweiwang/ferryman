# Contributing

Thanks for contributing to Ferryman.

## Before You Start

- Read the root [README.md](README.md)
- Use the local hook setup:

```bash
git config core.hooksPath .githooks
```

- Do not commit `.env` files, local secrets, signing assets, or generated release artifacts

## Development Setup

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

This repository expects backend work and tests to run in the Conda environment:

```bash
conda activate ferryman
cd backend
python -m pytest
```

If a test needs the local machine database or other non-sandboxed resources,
run it outside a restricted sandbox.

## Pull Requests

- Keep changes scoped
- Prefer the existing architecture and patterns in the codebase
- Add or update tests when behavior changes
- Update docs when user-facing behavior, setup, or policy changes
- Make sure local hooks pass before pushing

## Security

- Never commit API keys, tokens, certificates, or notarization material
- Use example files such as `frontend/.env.release.example` instead of local values
- If you discover a leak, rotate the secret and clean git history before release
