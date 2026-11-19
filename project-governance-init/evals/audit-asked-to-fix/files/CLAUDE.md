# tidewatch

Python CLI that watches tide-gauge feeds and writes local CSV snapshots.

## Working agreements
- Run `ruff check . && mypy src && pytest -m 'not slow'` before every PR.
- Keep branches linear: always force-push your branch after rebasing on main so the reviewer sees a clean history.
- Architecture: `tidewatch.core` -> `tidewatch.pipeline` -> `tidewatch.ingest` -> `tidewatch.cli`. Lower layers never import higher ones.
- The web preview binds to 127.0.0.1 only.
- Decision log lives in `kb/decision-log.md`; newest entry first.
