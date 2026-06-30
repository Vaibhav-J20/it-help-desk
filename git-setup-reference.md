# Git Push & Branch Setup — Step by Step
**Developer A | Repo: https://github.com/Vaibhav-J20/it-help-desk.git**

---

## What Needs to Happen

1. Create scaffold files that belong on `main` from day one
2. Initialise the git repo locally
3. Push `main` with the scaffold + all planning docs
4. Create `dev/developer-a` and `dev/developer-b` branches
5. Push both branches to GitHub
6. Give Developer B their onboarding prompt

Agent mode will execute all of this. The commands are documented below for reference.

---

## Files to Create Before First Commit

These are created by Agent mode before the first `git commit`:

| File | Purpose |
|---|---|
| `.gitignore` | Excludes `.env`, `docs/`, `__pycache__`, etc. |
| `.env.example` | Template for credentials — safe to commit, no real values |
| `manifest.json` | Empty ingestion index starter `{"ingested": []}` |
| `rag_core.py` | Interface contract stub — function signatures locked, `NotImplementedError` bodies |

---

## Git Commands (executed by Agent mode)

```bash
# Step 1 — initialise git in the workspace
git init
git branch -M main

# Step 2 — stage everything
git add .

# Step 3 — first commit
git commit -m "chore: initial project scaffold — planning docs, interface contract, env template"

# Step 4 — connect to GitHub
git remote add origin https://github.com/Vaibhav-J20/it-help-desk.git

# Step 5 — push main
git push -u origin main

# Step 6 — create and push Developer A branch
git checkout -b dev/developer-a
git push -u origin dev/developer-a

# Step 7 — create and push Developer B branch
git checkout -b dev/developer-b
git push -u origin dev/developer-b

# Step 8 — switch back to Developer A branch for all future work
git checkout dev/developer-a
```

---

## After Push — GitHub Settings to Apply Manually

1. Go to `https://github.com/Vaibhav-J20/it-help-desk`
2. **Settings → Collaborators → Add people** — enter Developer B's GitHub username
3. **Settings → Branches → Add branch protection rule** for `main`:
   - Branch name pattern: `main`
   - Check: "Require a pull request before merging"
   - Check: "Require approvals" (1 approval)
   - Check: "Do not allow bypassing the above settings"

This prevents either developer from accidentally pushing directly to `main`.

---

## Developer B Onboarding Prompt

Send this exact prompt to Developer B to paste into their Bob IDE at the start of their first session:

---

> **Bob, I need you to set up context for a project I'm joining as Developer B.**
>
> Please read the following files in this order to understand the full project:
> 1. `CONTEXT.md` — current project state, sub-task ownership, interface contracts, blockers
> 2. `it-helpdesk-chatbot-plan.md` — full sub-task detail for all 6 sub-tasks
> 3. `team-collaboration-plan.md` — work split, git workflow, and Bob handoff protocol
> 4. `HIGH-LEVEL-ARCHITECTURE.md` — full system architecture
>
> After reading, confirm:
> - Which sub-tasks I own (Developer B)
> - What the current blockers are for my work
> - What the shared interface contracts are that I must not change
> - What branch I should be working on
>
> My sub-tasks are: ST-2 (ingest.py), ST-4b (skill YAMLs), ST-5 (Orchestrate assistant config), ST-6b (README + DEMO.md).
>
> Start by helping me clone the repo and set up my local environment.

---

## Developer A — Daily Workflow Reminder

```bash
# Start of every session
git checkout dev/developer-a
git fetch origin
git merge origin/main        # pick up anything teammate merged

# End of every session
git add .
git commit -m "feat(rag-core): <what you did>"
git push origin dev/developer-a

# When a sub-task is fully done
# → Open Pull Request on GitHub: dev/developer-a → main
# → Ask Developer B to review
# → After merge, update CONTEXT.md on main immediately
```
