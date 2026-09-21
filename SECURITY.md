# Security
 drawings stay local by default. Only `src/cadcraft/verifier/jev_judge.py` touches the network and only when `TYPESAFE_API_KEY` is set and `--with-jev` is passed.
- Never commit `reference/private/`, `.env`, or customer drawings. They are git-ignored.
- DXF previews render locally via ezdxf/matplotlib; no telemetry.
- Report suspected leaks to the repo owner (tinkeragora).
