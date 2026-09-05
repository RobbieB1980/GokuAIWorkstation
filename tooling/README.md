# GokuAI tracked tooling

Files under `tooling/` are **committed to GitHub** (unlike `projects/` and `Data/`, which are gitignored).

| Path | Purpose |
|---|---|
| `legacy-converter-workspace-overlay/` | NeoForge 26.2 Fix-in-Grok skills, agents, workflows, Agents.md, destination-Java helpers |

Keep this tree updated when migration skills change, then push GokuAIWorkstation so a fresh clone can restore them with:

```powershell
.\scripts\Sync-LegacyConverterWorkspace.ps1 -Workspace <path> -SkillsOnly
```
