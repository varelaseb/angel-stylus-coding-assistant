# sift-stylus

Installs the Sift Codex skills:
- `sift-stylus-porting-auditor`
- `sift-stylus-research`
- `sift-stylus-code-helper`

## Quick install (both)

```bash
npx sift-stylus \
  --repo getFairAI/angel-stylus-coding-assistant
```

## Install one skill only

```bash
npx sift-stylus \
  --repo getFairAI/angel-stylus-coding-assistant \
  --skills sift-stylus-research
```

## Options

- `--repo <owner/repo>`: required GitHub repository containing skills.
- `--ref <git-ref>`: branch/tag/commit. Default: `main`.
- `--skills <csv>`: comma-separated skill names.
- `--skills-root <path>`: root path in repo containing skill folders. Default: `skills`.
- `--target <path>`: install root. Default: `~/.codex/skills`.
- `--force`: overwrite existing installs.
