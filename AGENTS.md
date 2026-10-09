# TechTim GCP Panel Common Rules

- When the user calls a requirement a `공통규칙`, treat it as a reusable convention for every current and future Google Cloud game-server panel in this repository. Record new common rules in this file without waiting for a separate reminder.
- Every server file explorer must visually distinguish folders and regular files with game-appropriate icons.
- UTF-8 configuration text files in a server file explorer must open in a large editor dialog when clicked. The editor must support direct editing, explicit save, dirty-state feedback, and `Ctrl/Cmd+S`.
- File editing must remain locked while the game server is running. Server-side checks must reject traversal, symbolic links, binary data, unsupported file types, and files over the configured editor size limit.
