# RB Legacy Java Converter — standing orders

**Track:** detected source **>= 1.20.1** → target **NeoForge 26.2** only.  
Pre-1.20.1 jars are **out of scope**. Legacy **1.20.1 → 26.1** is frozen.

## Always

1. Detect the artifact's real Minecraft/NeoForge version; do not assume every job starts at 1.20.1.
2. At session start read `.grok/rules/knowledge-sources.md` and `.grok/rules/session-knowledge-context.md`.
3. Knowledge lives outside the workspace (`C:\gokuai\Data`, allowlisted roots). Do not copy framework trees into the mod project.
4. Retrieval order: **failed-output packet → 262r → solved cases → primer_changes (one shard) → exact 26.2 physical source → invent + write back**.
5. Success = destination-Java **`gradlew build`** producing `build/libs/*.jar` (not `compileJava` alone).
6. Encode durable remaps into `tools/Convert-Forge1201-ToNeoForge262.ps1` **and** `C:\gokuai\Data\262r` (+ `catalog.json`).
7. Do **not** invent a permanent client renderer compile-gate when Entity Render State work is unfinished.

## Destination Java

NeoForge 26.2 → **JDK 25**. Never probe ambient/source Java 8 first.

```powershell
powershell -NoProfile -File tools\Build-WithDestinationJava.ps1 -ProjectRoot "<project-or-failed-output>"
```

## Token discipline

- Keep always-on text short (this file + rules). Load playbooks via skills.
- Open **one** 262r shard and **one** primer shard at a time.
- Parent builds a capped evidence packet before delegating; workers do not rediscover the corpus.
- Prefer a **fresh session per error family** after a green build or finished family (see skill `repair-failed-262-output`).

## On-demand playbooks (skills)

| Skill | When |
|---|---|
| `minecraft-knowledge` | API / mapping / primer / MCP lookup |
| `migrate-neoforge-262` | Full convert / migrate to 26.2 |
| `repair-failed-262-output` | Fix-in-Grok / failed output folder |
| `encode-262r-remap` | Persist a proven fix into 262r + converter |
| `validate-destination-build` | Compile/build with destination JDK |

## Delegation (summary)

Parent owns discovery. Workers receive a bounded packet (task, files, ≤4 target excerpts, mappings, errors, validation command). One local worker at a time on the single GPU.

| Agent | Use |
|---|---|
| `mc-research` | Read-only shard/excerpt gathering |
| `mc-fast` | Mechanical known remaps |
| `mc-code` | Default multi-file implementer |
| `mc-reviewer` | Independent review vs packet + build |

Spawn contract: `.grok/skills/migrate-neoforge-262/references/spawn-packet-contract.md`  
Workflow (optional): `/repair-neoforge-262` with `args.failed_output`  
Lint: `tools/Lint-MigrationSkills.ps1`  
Details: skills above + GokuAI root `AGENTS.md`.
