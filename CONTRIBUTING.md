# Contributing to .hdox

Thanks for helping! HDOX v1.0.0 is ready for contributions to shape the format and the tooling.

## Setup (2 minutes)

```bash
git clone https://github.com/HashimHilal-QUT/HDOX && cd HDOX
cd packages/cli-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # all tests should pass
```

TypeScript SDK: `cd packages/sdk-ts && npm ci && npm run build`.

## Ground rules

- **Bug fix?** Add a failing test first, then fix it.
- **Format change?** Update `spec/SPECIFICATION.md`, the manifest schema (both copies: `spec/` and
  `packages/cli-python/hdox/schema/` – a test checks they match), the Python validator and the TypeScript SDK together.
- Keep the safety defaults: no scripts, no network, safe paths. Changes that weaken them need a written rationale in the PR.
- Small, focused PRs are easiest to review. Run `pytest` before pushing.

## Where to start

See the "Help wanted" list in the README. Items marked 🟢 are good first contributions.
For larger changes, open an issue to discuss the design first.

By contributing you agree that your work is released under the project's [MIT license](LICENSE).
