# Semantic event evidence

`live-legacy-migration.json` records a migration run against a SQLite backup of
the active isolated revision-16 bridge database. The live database was not opened
by the new event store and was not modified.

The proof establishes ordered import, complete cursor read-back and idempotent
re-import for terminal legacy commands and committed Native dialogue entries. It
does not upgrade legacy command acknowledgements into independently observed game
outcomes. Historical dialogue rows do not contain the scene ID or a semantic
runtime revision, so imported events retain an explicit legacy scope and caveat.
