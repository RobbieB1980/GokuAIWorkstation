# Legacy Converter workspace overlay (tracked in GokuAI)

Durable copy of Fix-in-Grok / migration skills so they are not lost if `projects/` is wiped (that tree is gitignored).

## Contents

- `.grok/skills/` — repair/migrate/encode/validate/minecraft-knowledge
- `.grok/agents/` — mc-research, mc-fast, mc-code, mc-reviewer
- `.grok/workflows/` — repair-neoforge-262
- `.grok/rules/` — knowledge pointers
- `Agents.md` — slim standing orders
- `tools/` — Build-WithDestinationJava.ps1, Lint-MigrationSkills.ps1

## Sync into a workspace

```powershell
# Any workspace (skills only)
.\scripts\Sync-LegacyConverterWorkspace.ps1 -Workspace "D:\my-mod-26.2" -SkillsOnly

# Converter project (full tools when packaging repo present)
.\scripts\Sync-LegacyConverterWorkspace.ps1 -Workspace "C:\gokuai\projects\RB-Legacy-Java-Converter"
```

`Open-GokuAIWorkspace.ps1` runs this automatically before every launch (including new workspaces).

Canonical product packaging also keeps a twin under:
`projects\_upstream\LegacyJavaConverter\gokuai-workspace-overlay\`
(on LegacyJavaConverter GitHub).
