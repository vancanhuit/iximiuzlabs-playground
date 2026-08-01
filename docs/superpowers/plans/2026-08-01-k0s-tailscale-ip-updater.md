# k0s Tailscale IP Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `uv`-runnable Python utility that discovers every configured node's current Tailscale IPv4 address and safely updates the k0sctl YAML.

**Architecture:** Keep Tailscale inventory parsing and YAML transformation as pure functions, then wrap them in a small CLI that performs one `tailscale status --json` call and an atomic file replacement. Use `ruamel.yaml` round-trip mode so unrelated YAML formatting and values remain stable.

**Tech Stack:** Python 3.12+, uv PEP 723 script metadata, `ruamel.yaml==0.19.0`, standard-library `unittest`, Tailscale CLI

## Global Constraints

- Update only `docs/k0s/k0s.yaml`; README addresses remain examples.
- Match every configured hostname to exactly one online Tailscale node before changing memory or disk.
- Accept one unique IPv4 in `100.64.0.0/10` per configured host.
- Update only `privateAddress`, `ssh.address`, and existing controller address entries in API SANs.
- Preserve unrelated SANs, YAML ordering, formatting, quoting, and file mode.
- Run subprocesses without a shell and with a finite timeout.
- Support `--dry-run` and `--config`; default the config path relative to the repository, not the current directory.

---

## File Structure

- `scripts/update_k0s_tailscale_ips.py`: PEP 723 metadata, inventory validation, round-trip YAML transformation, atomic persistence, and CLI.
- `tests/test_update_k0s_tailscale_ips.py`: fixture-driven unit tests requiring no live tailnet.
- `docs/k0s/README.md`: prerequisites and exact dry-run, update, and validation commands.

### Task 1: Inventory and YAML Transformation

**Files:**
- Create: `scripts/update_k0s_tailscale_ips.py`
- Create: `tests/test_update_k0s_tailscale_ips.py`

**Interfaces:**
- Produces: `UpdateError`, `AddressChange`, `resolve_addresses(status, hostnames) -> dict[str, str]`, and `update_document(document, addresses) -> list[AddressChange]`.
- Consumes: k0sctl mappings loaded by a round-trip `ruamel.yaml.YAML()` instance and Tailscale status mappings containing `Self` and `Peer`.

- [ ] **Step 1: Write failing happy-path tests**

Create a two-controller, one-worker YAML fixture and a Tailscale status fixture. Assert that `resolve_addresses()` returns all three hostname mappings and `update_document()` changes both host address fields plus only the two controller IP SANs:

```python
class UpdateDocumentTests(unittest.TestCase):
    def test_updates_host_addresses_and_controller_sans(self) -> None:
        document = YAML().load(CONFIG_YAML)
        addresses = resolve_addresses(STATUS, ["control-plane-01", "control-plane-02", "node-01"])

        changes = update_document(document, addresses)

        hosts = document["spec"]["hosts"]
        self.assertEqual(hosts[0]["privateAddress"], "100.64.0.11")
        self.assertEqual(hosts[0]["ssh"]["address"], "100.64.0.11")
        self.assertEqual(hosts[2]["privateAddress"], "100.64.0.21")
        self.assertEqual(
            document["spec"]["k0s"]["config"]["spec"]["api"]["sans"],
            ["control-plane-01", "control-plane-02", "api.example.test", "100.64.0.11", "100.64.0.12"],
        )
        self.assertEqual(len(changes), 3)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run --with 'ruamel.yaml==0.19.0' \
  python -m unittest discover -s tests -p 'test_update_k0s_tailscale_ips.py' -v
```

Expected: FAIL because `scripts.update_k0s_tailscale_ips` does not exist.

- [ ] **Step 3: Implement the pure transformation path**

Start the script with executable uv metadata:

```python
#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["ruamel.yaml==0.19.0"]
# ///
```

Define `AddressChange` as a frozen dataclass with `hostname`, `old_address`, and
`new_address`. Implement `resolve_addresses()` by combining `Self` with
`Peer.values()`, indexing `HostName` and the first label of `DNSName`, and
selecting the single IPv4 in `100.64.0.0/10`. Treat `Self` as online; require
`Online is True` for peers. Reject duplicate hostname aliases and reused IPs
with `UpdateError`.

Implement `update_document()` in two phases:

1. Validate the `spec.hosts` list, unique hostnames, required address mappings,
   controller roles, and one exact SAN occurrence for each controller's old
   private address.
2. Replace controller SAN entries in place, then update each host's
   `privateAddress` and `ssh.address`.

Do not mutate the document until all structural validation succeeds.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command. Expected: all focused tests PASS with no warnings.

- [ ] **Step 5: Commit the pure updater**

```bash
git add scripts/update_k0s_tailscale_ips.py tests/test_update_k0s_tailscale_ips.py
git commit -m "feat: add Tailscale IP updater core"
```

### Task 2: Validation, Dry Run, and Atomic Persistence

**Files:**
- Modify: `scripts/update_k0s_tailscale_ips.py`
- Modify: `tests/test_update_k0s_tailscale_ips.py`

**Interfaces:**
- Consumes: `resolve_addresses()` and `update_document()` from Task 1.
- Produces: `load_status() -> dict[str, object]`, `update_file(config_path, status, dry_run=False) -> list[AddressChange]`, and `main(argv=None) -> int`.

- [ ] **Step 1: Add failing validation and file-safety tests**

Add table-driven subtests that alter the fixture to create missing, offline,
duplicate, non-CGNAT, multiple-IPv4, and reused-address cases. Each must raise
`UpdateError` with the hostname or address in the message.

Add temporary-file tests with these assertions:

```python
def test_dry_run_does_not_write(self) -> None:
    config_path = self.write_config(CONFIG_YAML)
    original = config_path.read_bytes()

    changes = update_file(config_path, STATUS, dry_run=True)

    self.assertEqual(len(changes), 3)
    self.assertEqual(config_path.read_bytes(), original)

def test_validation_failure_does_not_write(self) -> None:
    config_path = self.write_config(CONFIG_YAML)
    original = config_path.read_bytes()

    with self.assertRaises(UpdateError):
        update_file(config_path, STATUS_WITH_MISSING_NODE)

    self.assertEqual(config_path.read_bytes(), original)
```

Also assert a successful write preserves `stat.S_IMODE(config_path.stat().st_mode)`
and changes no textual lines except the expected address scalars.

- [ ] **Step 2: Run the focused tests and verify RED**

Run the Task 1 test command. Expected: FAIL because `update_file()` and the full
validation behavior are absent.

- [ ] **Step 3: Implement command and persistence boundaries**

`load_status()` must execute:

```python
subprocess.run(
    ["tailscale", "status", "--json"],
    check=True,
    capture_output=True,
    text=True,
    timeout=15,
    env={**os.environ, "TAILSCALE_BE_CLI": "1"},
)
```

Convert missing executables, timeouts, non-zero exits, invalid JSON, and an
unexpected top-level JSON type into concise `UpdateError` messages.

`update_file()` must load with `YAML(typ="rt")`, enable quote preservation,
perform all in-memory validation, and return without dumping for `dry_run`.
For a real update, dump to a named temporary file in the target directory,
copy the original mode, flush and `os.fsync()`, then call `os.replace()`.
Delete the temporary file after any exception.

`main()` must parse:

```text
--config PATH   k0sctl config (default: <repo>/docs/k0s/k0s.yaml)
--dry-run       print planned changes without writing
```

Print one `hostname: old -> new` line per configured host, followed by either
`Dry run: no files written`, `Updated <path>`, or `No address changes`.
Print `error: <message>` to stderr and return 1 for `UpdateError`.

- [ ] **Step 4: Run tests and CLI syntax checks**

```bash
uv run --with 'ruamel.yaml==0.19.0' \
  python -m unittest discover -s tests -p 'test_update_k0s_tailscale_ips.py' -v
uv run scripts/update_k0s_tailscale_ips.py --help
```

Expected: all tests PASS and help exits 0 with both options listed.

- [ ] **Step 5: Commit the safe CLI**

```bash
git add scripts/update_k0s_tailscale_ips.py tests/test_update_k0s_tailscale_ips.py
git commit -m "feat: safely update k0s node addresses"
```

### Task 3: Runbook Integration and End-to-End Validation

**Files:**
- Modify: `docs/k0s/README.md`

**Interfaces:**
- Consumes: `uv run scripts/update_k0s_tailscale_ips.py [--dry-run]` from Task 2.
- Produces: a reproducible pre-bootstrap workflow for tailnet-specific node addresses.

- [ ] **Step 1: Update prerequisites and bootstrap workflow**

Replace the manual-replacement note below the topology table with a statement
that the addresses are examples and the updater populates the operational YAML.
In `Prerequisites`, require the control host to be connected to the target
tailnet and every configured hostname to appear online in `tailscale status`.

Before `## 1. Validate the k0sctl plan`, add:

````markdown
## 1. Update Tailscale node addresses

Preview and apply the tailnet-specific addresses:

```bash
uv run scripts/update_k0s_tailscale_ips.py --dry-run
uv run scripts/update_k0s_tailscale_ips.py
```

The command updates each host's `privateAddress` and `ssh.address` and the
controller API certificate SANs in `docs/k0s/k0s.yaml`. It aborts without
writing unless every configured node is online and has one unique Tailscale
IPv4 address.
````

Renumber the existing bootstrap sections after inserting the new step.

- [ ] **Step 2: Run static and fixture validation**

```bash
uv run --with 'ruamel.yaml==0.19.0' \
  python -m unittest discover -s tests -p 'test_update_k0s_tailscale_ips.py' -v
uv run scripts/update_k0s_tailscale_ips.py --help
git diff --check
```

Expected: tests PASS, CLI help exits 0, and the diff check reports no errors.

- [ ] **Step 3: Run live dry-run validation**

```bash
uv run scripts/update_k0s_tailscale_ips.py --dry-run
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

Expected: all eight configured hostnames resolve to unique `100.64.0.0/10`
addresses, the updater reports no write, and k0sctl accepts the resulting
cluster definition.

- [ ] **Step 4: Commit runbook integration**

```bash
git add docs/k0s/README.md
git commit -m "docs: automate k0s Tailscale addresses"
```

- [ ] **Step 5: Review the complete change**

```bash
git status --short
git log -4 --oneline
git diff HEAD~3..HEAD --check
```

Expected: no uncommitted files, three focused implementation commits after the
design and plan commits, and no whitespace errors across the complete change.
