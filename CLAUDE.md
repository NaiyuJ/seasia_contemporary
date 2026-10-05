# Project rules for Claude

Empirical social-science project on Chinese investment and Chinese-Indonesian
identity. Python 3.11. Unit of analysis is the kabupaten/kota (BPS 4-digit code).

- `data/` is git-ignored. Never commit raw data, images or API keys. Read the
  Google key from `GOOGLE_MAPS_API_KEY` only.
- Every result must come from a script that can be rerun from `data/raw`. Do not
  report numbers computed ad hoc in chat.
- Run `python -m pytest -q` before committing changes to `signage/`.
- When adding a measurement module, add a `docs/<module>_design.md` describing
  what it measures and the identification caveats.
