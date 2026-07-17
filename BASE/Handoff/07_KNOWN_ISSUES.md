# Known Issues

1. Real ASR quality is still below the user's bar.
The fixture benchmark improved, and app defaults now match that benchmark path, but real UI output still needs to be judged by the user.

2. First usable output is still slower than intended.
The latest benchmark emitted first text at about `3.59s`, which is better than before but still not close to the user's desired live feel.

3. The duplicate first transcript row needs re-verification.
The UI now replaces an existing row when a backend replacement broadcast uses the same `segment_id`, which targets the observed duplicate-row path. It still needs a real UI run against the updated backend.

4. Session and feed controls are easy to misunderstand.
The app distinguishes session creation/start from feed start/stop, but the UI does not explain that clearly enough for testing flow.

5. `mlx` is still not the most trustworthy benchmark path today.
The app now defaults to `faster-whisper`; `mlx` remains available with `TRANSCOM_ASR_BACKEND=mlx` and should be revisited only after the faster-whisper path is satisfactory.

6. Password visibility remains a beta-only compromise.
`backend/auth/service.py` stores `visible_password` for admin UX. That is acceptable for local/beta operations, not for hardened production security.
