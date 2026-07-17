# TODO

| Status | Priority | Task |
| --- | --- | --- |
| open | P0 | Improve real ASR quality on the mixed demo/intercom feed; treat user-perceived quality as the main gate |
| open | P0 | Reduce first usable transcript latency from about `3.54s` toward the intended live target |
| open | P0 | Re-run real UI test against the updated backend to confirm duplicate first transcript row is gone |
| open | P0 | Clarify or simplify the session/create/start/feed UX so testing is not confusing |
| open | P1 | Revisit utterance commit logic so final rows are coherent and not over-fragmented |
| open | P1 | Re-check speaker matching on final VAD segments only and verify it does not degrade ASR timing |
| open | P1 | Validate the `mlx` runtime path again after the `faster-whisper` path is satisfactory |
| open | P1 | Re-run browser-level end-to-end testing after the next ASR/stabilizer changes |
| future | P2 | Design a Finder-backed transcript library: recent transcripts in a collapsible sidebar, synchronized audio playback, editing, reveal in Finder, export, and archive actions; see `10_FUTURE_TRANSCRIPT_LIBRARY.md` |
| done | P1 | Add audible browser monitoring for demo/file mode when `Start Feed` is pressed |
| done | P0 | Audit why the fixture benchmark improved while real UI output was still poor: UI/default launch paths used different ASR/language defaults |
| done | P0 | Align default local ASR path with the verified `faster-whisper` benchmark path |
| done | P0 | Stop beta launcher from forcing German-only transcription on the mixed German/English feed |
| done | P0 | Add targeted UI replacement for updated transcript segment IDs so replacement broadcasts do not append duplicate rows |
| done | P1 | Restore usable Audio File / Demo WAV controls in the UI |
| done | P1 | Keep file-source mode stable during frontend state refreshes |
| done | P1 | Add auth-disabled local test mode for faster UI iteration |
| done | P1 | Improve the fixture benchmark over the older `0.4167` WER baseline |
| done | P2 | Populate and synchronize the full `BASE` handoff folder |
