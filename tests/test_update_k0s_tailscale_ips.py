"""Tests for k0s Tailscale IP updater."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq

from scripts.update_k0s_tailscale_ips import (
    UpdateError,
    resolve_addresses,
    update_document,
    update_file,
)

# k0sctl YAML fixture: 2 controllers + 1 worker
CONFIG_YAML = """
apiVersion: k0sctl.k0sproject.io/v1beta1
kind: Cluster
metadata:
  name: k0s-cluster
spec:
  hosts:
  - role: controller
    ssh:
      address: 10.0.1.11
      user: root
      port: 22
      keyPath: ~/.ssh/id_rsa
    privateAddress: 10.0.1.11
    hostname: control-plane-01
  - role: controller
    ssh:
      address: 10.0.1.12
      user: root
      port: 22
      keyPath: ~/.ssh/id_rsa
    privateAddress: 10.0.1.12
    hostname: control-plane-02
  - role: worker
    ssh:
      address: 10.0.1.21
      user: root
      port: 22
      keyPath: ~/.ssh/id_rsa
    privateAddress: 10.0.1.21
    hostname: node-01
  k0s:
    version: v1.28.4+k0s.0
    config:
      spec:
        api:
          sans:
          - control-plane-01
          - control-plane-02
          - api.example.test
          - 10.0.1.11
          - 10.0.1.12
"""

# Tailscale status fixture: Self + 2 peers
STATUS = {
    "Self": {
        "HostName": "control-plane-01",
        "DNSName": "control-plane-01.example.ts.net.",
        "TailscaleIPs": ["100.64.0.11", "fd7a:115c:a1e0::1"],
    },
    "Peer": {
        "peer-id-02": {
            "HostName": "control-plane-02",
            "DNSName": "control-plane-02.example.ts.net.",
            "TailscaleIPs": ["100.64.0.12", "fd7a:115c:a1e0::2"],
            "Online": True,
        },
        "peer-id-21": {
            "HostName": "node-01",
            "DNSName": "node-01.example.ts.net.",
            "TailscaleIPs": ["100.64.0.21", "fd7a:115c:a1e0::3"],
            "Online": True,
        },
    },
}


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

    def test_preserves_sans_commentedseq_object_identity(self) -> None:
        """Verify that update_document mutates the original CommentedSeq in place, preserving object identity and metadata."""
        document = YAML().load(CONFIG_YAML)
        addresses = resolve_addresses(STATUS, ["control-plane-01", "control-plane-02", "node-01"])

        # Capture the original sans object reference and type
        sans_before = document["spec"]["k0s"]["config"]["spec"]["api"]["sans"]
        sans_id_before = id(sans_before)

        # Verify it's a CommentedSeq before mutation
        self.assertIsInstance(sans_before, CommentedSeq)

        update_document(document, addresses)

        # Capture the sans object after mutation
        sans_after = document["spec"]["k0s"]["config"]["spec"]["api"]["sans"]
        sans_id_after = id(sans_after)

        # Assert object identity preserved (same object, mutated in place)
        self.assertEqual(sans_id_before, sans_id_after, "SAN list object identity must be preserved")

        # Assert CommentedSeq type preserved
        self.assertIsInstance(sans_after, CommentedSeq, "SAN list must remain a CommentedSeq")

        # Verify content updated correctly
        self.assertEqual(
            list(sans_after),
            ["control-plane-01", "control-plane-02", "api.example.test", "100.64.0.11", "100.64.0.12"],
        )


class ResolveAddressesValidationTests(unittest.TestCase):
    """Test validation edge cases in resolve_addresses."""

    def test_missing_hostname_raises_error(self) -> None:
        """Hostname not in status should raise UpdateError."""
        with self.assertRaises(UpdateError) as ctx:
            resolve_addresses(STATUS, ["nonexistent-host"])
        self.assertIn("nonexistent-host", str(ctx.exception))

    def test_offline_node_raises_error(self) -> None:
        """Offline peer should raise UpdateError."""
        status_with_offline = {
            "Self": STATUS["Self"],
            "Peer": {
                "peer-offline": {
                    "HostName": "offline-node",
                    "DNSName": "offline-node.example.ts.net.",
                    "TailscaleIPs": ["100.64.0.99"],
                    "Online": False,
                }
            },
        }
        with self.assertRaises(UpdateError) as ctx:
            resolve_addresses(status_with_offline, ["offline-node"])
        self.assertIn("offline-node", str(ctx.exception))

    def test_duplicate_hostname_raises_error(self) -> None:
        """Duplicate hostname with different IPs should raise UpdateError."""
        status_with_duplicate = {
            "Self": {
                "HostName": "duplicate",
                "DNSName": "duplicate.example.ts.net.",
                "TailscaleIPs": ["100.64.0.1"],
            },
            "Peer": {
                "peer-dup": {
                    "HostName": "duplicate",
                    "DNSName": "duplicate.example.ts.net.",
                    "TailscaleIPs": ["100.64.0.2"],
                    "Online": True,
                }
            },
        }
        with self.assertRaises(UpdateError) as ctx:
            resolve_addresses(status_with_duplicate, ["duplicate"])
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_non_cgnat_ip_rejected(self) -> None:
        """IP outside 100.64.0.0/10 should be ignored."""
        status_non_cgnat = {
            "Self": {
                "HostName": "public-node",
                "DNSName": "public-node.example.ts.net.",
                "TailscaleIPs": ["100.63.0.1"],  # Just outside 100.64.0.0/10
            },
            "Peer": {},
        }
        with self.assertRaises(UpdateError) as ctx:
            resolve_addresses(status_non_cgnat, ["public-node"])
        self.assertIn("public-node", str(ctx.exception))

    def test_multiple_ipv4_raises_error(self) -> None:
        """Multiple IPv4 addresses in CGNAT range should raise UpdateError."""
        status_multi_ip = {
            "Self": {
                "HostName": "multi-ip",
                "DNSName": "multi-ip.example.ts.net.",
                "TailscaleIPs": ["100.64.0.1", "100.64.0.2"],
            },
            "Peer": {},
        }
        with self.assertRaises(UpdateError) as ctx:
            resolve_addresses(status_multi_ip, ["multi-ip"])
        self.assertIn("multi-ip", str(ctx.exception))


class UpdateFileTests(unittest.TestCase):
    """Test file I/O and atomic write behavior."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_config(self, content: str) -> Path:
        """Helper to write config to temp file."""
        config_path = self.temp_path / "k0s.yaml"
        config_path.write_text(content.strip() + "\n", encoding="utf-8")
        return config_path

    def test_dry_run_does_not_write(self) -> None:
        config_path = self.write_config(CONFIG_YAML)
        original = config_path.read_bytes()

        changes = update_file(config_path, STATUS, dry_run=True)

        self.assertEqual(len(changes), 3)
        self.assertEqual(config_path.read_bytes(), original)

    def test_validation_failure_does_not_write(self) -> None:
        config_path = self.write_config(CONFIG_YAML)
        original = config_path.read_bytes()

        status_with_missing_node = {
            "Self": STATUS["Self"],
            "Peer": {},  # Missing the other nodes
        }

        with self.assertRaises(UpdateError):
            update_file(config_path, status_with_missing_node)

        self.assertEqual(config_path.read_bytes(), original)

    def test_successful_write_preserves_permissions(self) -> None:
        """Atomic write should preserve file mode."""
        config_path = self.write_config(CONFIG_YAML)
        original_mode = stat.S_IMODE(config_path.stat().st_mode)
        config_path.chmod(0o600)  # Set specific permissions

        update_file(config_path, STATUS, dry_run=False)

        final_mode = stat.S_IMODE(config_path.stat().st_mode)
        self.assertEqual(final_mode, 0o600)

    def test_successful_write_changes_only_addresses(self) -> None:
        """Atomic write should change only expected address lines."""
        config_path = self.write_config(CONFIG_YAML)
        original_lines = config_path.read_text(encoding="utf-8").splitlines()

        update_file(config_path, STATUS, dry_run=False)

        new_lines = config_path.read_text(encoding="utf-8").splitlines()

        # Count changed lines
        changed_lines = []
        for i, (old, new) in enumerate(zip(original_lines, new_lines)):
            if old != new:
                changed_lines.append((i + 1, old.strip(), new.strip()))

        # We expect exactly 8 changes:
        # - 3 hosts * 2 addresses each (ssh.address + privateAddress) = 6
        # - 2 controller IPs in SANs = 2
        self.assertEqual(len(changed_lines), 8)

        # Verify all changes are address replacements
        for line_num, old, new in changed_lines:
            # Each changed line should be an IP address change
            self.assertTrue("10.0.1." in old or old.startswith("address:"))
            self.assertTrue("100.64.0." in new or new.startswith("address:"))


if __name__ == "__main__":
    unittest.main()
