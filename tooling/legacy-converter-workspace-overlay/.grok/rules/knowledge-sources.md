# Live Minecraft Knowledge Sources

- Declared source version: **1.20.1** (must be >= 1.20.1; detect exact artifact version)
- Declared target version: **26.2**
- Conversion track: **modern detected-source → 26.2** (legacy 1.20.1 → 26.1 is frozen)

## Hard rules

- Workspace = the mod being migrated. Knowledge = the registered roots below.
- Index locates. Source directories teach.
- Detect the artifact exact Minecraft version. Do not hardcode every job to start at 1.20.1.
- Prefer compact `primer_changes` ledger/shards for `1.20.1 → 26.2` before opening full primer `index.md` bodies.
- Before API edits, resolve the primer chain `1.20.1 → 26.2` (ledger first) and build migration evidence so no intermediate delta is skipped.
- Target API claims must be supported by files indexed as exact target version **26.2**.
- Do not grep the migration project for Forge/NeoForge API truth.
- Never treat an empty FTS search as proof that a version or API is absent.
- Never use an adjacent version as authoritative unless comparison is explicitly requested.
- Mapping translation must use minecraft-knowledge resolve_mapping with explicit namespaces.
- If the input jar/mod is older than 1.20.1, stop and report out-of-scope.
- Indexer policy: **GokuAI only** (`C:\gokuai\Data`). Do not register external `H:\` trees.

## Registered source roots

Policy: **GokuAI only** — index `C:\gokuai\Data` (`local`). External trees (e.g. `H:\GrokBuild_MF\Completed_Projects`) are not registered.

- `local` -> `C:\gokuai\Data` (27785 indexed files; available)

## Exact-version entrypoints

- Compact primer_changes ledger: `C:\gokuai\Data\NeoForge_Primers\26.2\primer_changes_1.20.1-to-26.2.md`
- Target primer (full, only if needed): `C:\gokuai\Data\_upstream\neoforge_primers\primers\26.2\index.md`
- Source Minecraft reference: `C:\gokuai\Data\Minecraft_Java_Server_Client\1.20.1\_SOURCE.json`
- Source MCPConfig: `C:\gokuai\Data\_upstream\mcpconfig\versions\release\1.20.1\config.json`
- Target Gradle reference: `C:\gokuai\Data\Exact_Version_Sources\NeoForge\26.2\gradlew`
- Primer_changes shards: `C:\gokuai\Data\NeoForge_Primers\26.2\primer_changes_1.20.1-to-26.2`
- 262-repair knowledge (category `262r`): `C:\gokuai\Data\262r`

- Mapping corpus: `C:\gokuai\Data\Minecraft_Mappings_Corpus\mappings.v3.1787973081.db` (ready)
