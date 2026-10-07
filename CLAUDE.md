# Working on this repo

Litefuse + Apache Doris (VeloDB Cloud) agent observability and evaluation demo.
Read `DESIGN.md` first: architecture, data flow, evaluation design, and the
**Known issues and next steps** list. `README.md` covers setup and `WALKTHROUGH.md` the demo script.

## Several agents share this checkout

More than one Claude Code session works in this directory at the same time, and they
all see the same files, the same `.env`, the same Docker stack, and the same Litefuse
project and VeloDB database. Follow these rules so you don't break each other's work.

1. **Start every task with `git status` and `git log --oneline -10`.** Uncommitted
   changes you did not make belong to another session. Do not revert, reformat or
   overwrite them. If you need to touch the same file, ask the user first.
2. **Commit each finished, verified change right away**, in small commits that only
   contain your own files (`git add <paths>`, never `git add -A`). The commit history is
   how the other sessions learn what changed, so write messages that say what and why.
3. **Use a worktree for anything larger than a quick fix**, or for work that runs while
   another session is editing: `claude --worktree <name>` (or the EnterWorktree tool).
   Commit there on a branch, then merge into `main` when it is done and verified.
4. **Shared runtime state needs a heads-up before you change it**:
   - `make down`, `make reset` (wipes volumes) or editing `deploy/docker-compose.yml`
     stops Litefuse for everyone.
   - Prompt labels (`support-system` `v1`, `v2`, `production`) and the `support-golden`
     dataset live in Litefuse and are used by every session's experiments.
   - Data in the VeloDB `litefuse` database.
   Ask the user first, or message the other sessions (ListAgents, then SendMessage).
5. **Keep `DESIGN.md` current.** When you change behaviour, tools, prompts, dataset
   cases or measured results, update the relevant section and the
   **Known issues and next steps** list in the same commit.
6. **Never commit `.env`** or any key, password or warehouse hostname. This repo is
   public on GitHub (`warheade/litefuse-Doris-agent-demo`).

## Checks before committing

```bash
uv run python -c "import demo.agent, demo.simulate, demo.eval.run_experiment, demo.verify_velodb"
make ask Q="Where is my order VO-1002?"     # needs `make up` and a configured .env
```
