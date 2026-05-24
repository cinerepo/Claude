# Watch Folders

This directory is the active processing zone for the Agent-Showcase.

## How to Use

1. Create a `.md` file with your content
2. Optionally add frontmatter to direct processing (see below)
3. Drop it into `incoming/`
4. Ask Claude to process the watch folder
5. Find your output in `output/`

## Frontmatter Reference

```markdown
---
type: summary | task | report | qa
title: Optional title
context: cinesys-profile | agent-registry | agent-capabilities
---
```

Omit `type` and the agent will auto-detect intent.

## Folders

| Folder | Purpose |
|---|---|
| `incoming/` | Drop zone — files waiting to be processed |
| `processed/` | Archive — files already handled (move here after processing) |
| `output/` | Results — generated output files land here |

## Naming Convention

Output files mirror the input filename with `-output` appended:

```
incoming/meeting-notes.md  →  output/meeting-notes-output.md
```
