# k0s Updater uv Project Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the updater test beside its script and replace PEP 723 dependencies with a locked, repository-local uv project environment.

**Architecture:** A root `pyproject.toml` declares Python and `ruamel.yaml`, while `uv.lock` pins the resolved environment and `uv sync` manages `.venv`. The updater remains a standalone script, and its co-located unittest continues to import the script through the `scripts` namespace package.

**Tech Stack:** Python 3.12+, uv 0.12.0, `ruamel.yaml==0.19.0`, standard-library `unittest`

## Global Constraints

- Preserve updater behavior and all 12 existing tests.
- Remove the PEP 723 inline metadata and `--script` execution mode.
- Store the test at `scripts/test_update_k0s_tailscale_ips.py`.
- Commit `pyproject.toml` and the uv-generated `uv.lock`; do not commit `.venv`.
- Use `uv sync` to create or update `.venv`, and `uv run` for commands.
- Keep `docs/k0s/k0s.yaml` unchanged and validate live discovery with `--dry-run` only.

---

### Task 1: Project Environment and Test Relocation

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock` using `uv lock`
- Modify: `.gitignore`
- Modify: `scripts/update_k0s_tailscale_ips.py`
- Move: `tests/test_update_k0s_tailscale_ips.py` to `scripts/test_update_k0s_tailscale_ips.py`

**Interfaces:**
- Produces: a synchronized `.venv` consumed by all `uv run` commands.
- Preserves: every public function and CLI option in `scripts/update_k0s_tailscale_ips.py`.

- [ ] **Step 1: Record the green pre-migration baseline**

```bash
uv run --with 'ruamel.yaml==0.19.0' \
  python -m unittest discover -s tests -p 'test_update_k0s_tailscale_ips.py' -v
```

Expected: all 12 tests PASS.

- [ ] **Step 2: Add project metadata and ignore the environment**

Create `pyproject.toml`:

```toml
[project]
name = "iximiuzlabs-playground"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "ruamel.yaml==0.19.0",
]

[tool.uv]
package = false
```

Append `.venv/` to `.gitignore`, preserving the existing Python cache rules.

- [ ] **Step 3: Relocate the test and remove inline dependencies**

Move the test without changing its assertions:

```bash
git mv tests/test_update_k0s_tailscale_ips.py scripts/test_update_k0s_tailscale_ips.py
```

Replace the updater header:

```python
#!/usr/bin/env -S uv run

"""k0s Tailscale IP updater - pure transformation core."""
```

Remove the complete PEP 723 `# /// script` block. Do not alter updater logic.

- [ ] **Step 4: Lock, synchronize, and verify the migrated test**

```bash
uv lock
uv sync --locked
uv run --locked python -m unittest scripts/test_update_k0s_tailscale_ips.py -v
uv run --locked scripts/update_k0s_tailscale_ips.py --help
```

Expected: `uv.lock` is created, `.venv` contains `ruamel.yaml==0.19.0`, all 12
tests PASS, and CLI help lists `--config` and `--dry-run`.

- [ ] **Step 5: Verify dependency ownership**

```bash
rg 'PEP 723|/// script|uv run --with|tests/test_update_k0s' \
  scripts pyproject.toml .gitignore
git status --short
git diff --check
```

Expected: no stale inline metadata or old test path; `.venv` is absent from
status; only the five intended tracked paths and generated lockfile changed.

- [ ] **Step 6: Commit the environment migration**

```bash
git add -A .gitignore pyproject.toml uv.lock scripts tests
git commit -m "build: migrate updater to uv project"
```

### Task 2: Runbook Integration and Live Validation

**Files:**
- Modify: `docs/k0s/README.md`

**Interfaces:**
- Consumes: `uv sync`, the locked `.venv`, and the co-located test from Task 1.
- Produces: reproducible setup and verification commands for operators.

- [ ] **Step 1: Document environment setup and test location**

After the existing `mise install` commands in `Prerequisites`, add:

```bash
uv sync --locked
uv run --locked python -m unittest scripts/test_update_k0s_tailscale_ips.py -v
```

State that `uv sync --locked` creates the repository-local `.venv` from
`pyproject.toml` and `uv.lock`. Keep the updater preview/apply commands in the
existing address-update section.

- [ ] **Step 2: Run static validation**

```bash
uv sync --locked
uv run --locked python -m unittest scripts/test_update_k0s_tailscale_ips.py -v
uv run --locked scripts/update_k0s_tailscale_ips.py --help
uv lock --check
git diff --check
```

Expected: all 12 tests PASS, CLI help exits 0, the lockfile is current, and no
whitespace errors are reported.

- [ ] **Step 3: Run live read-only validation**

```bash
uv run --locked scripts/update_k0s_tailscale_ips.py --dry-run
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

Expected: all eight configured hosts resolve without writing the YAML and
k0sctl accepts the unchanged cluster definition.

- [ ] **Step 4: Commit and review the runbook**

```bash
git add docs/k0s/README.md
git commit -m "docs: document updater uv environment"
git status --short
git diff HEAD~2..HEAD --check
```

Expected: a clean worktree and no whitespace errors across the migration.
