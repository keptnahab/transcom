# Future Concept: Finder-backed Transcript Library

Status: product idea for a later implementation wave, not current scope.

## Product direction

TransCom should not invent a hidden cloud-style document system. Finder remains
the source of truth for transcript storage. The app adds a compact, collapsible
library sidebar that makes existing transcripts easy to reopen without exposing
database paths or technical session details in the normal workflow.

## Proposed experience

- The sidebar lists recent transcripts with name, date, duration, and source type.
- Clicking an item opens its transcript in the main pane.
- If audio is available, playback is synchronized with transcript timestamps;
  clicking a transcript row seeks to that moment.
- Open transcripts can be corrected: text, speaker assignment, and title.
- The item menu offers: `Im Finder zeigen`, rename, export, archive, and delete
  with confirmation.
- `New transcript` remains the primary action. The library can stay collapsed
  while recording so the live interface remains simple.
- A Finder folder or transcript package can be opened through the native macOS
  open dialog and then appears in the recent list.

## Storage concept

Treat one transcript as one self-contained session folder (potentially presented
later as a macOS `.transcom` package), rather than as a loose text file. The
package owns metadata, the editable transcript database, exports, and optional
managed audio. External source audio should initially be referenced rather than
silently duplicated; copying it into the package can be an explicit option.

The current session structure already points in this direction:

- `session.json` for identity and metadata
- `transcript.db` for the editable canonical transcript
- `exports/` for TXT/CSV and future formats
- `profiles/` for session-related speaker data

## Questions to resolve before implementation

- Should imported audio remain external by default or be copied into the
  transcript package for portability?
- Should archived transcripts remain visible in a separate group or only in
  Finder?
- Which export should be the human-readable long-term format: TXT, JSON, SRT,
  or a combination?
- Should Finder moves be tracked through bookmarks/security-scoped access, or
  should moved packages simply be reopened manually?

## Guardrails

- Do not place file management controls in the primary live-recording flow.
- Do not expose raw database filenames or long absolute paths by default.
- Do not delete source audio when deleting a transcript unless it was explicitly
  copied into and owned by the transcript package.
- Keep the complete workflow local-first and offline-first.
