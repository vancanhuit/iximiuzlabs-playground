"""Tests for k0s Tailscale IP updater."""

import unittest
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq

from scripts.update_k0s_tailscale_ips import (
    resolve_addresses,
    update_document,
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


if __name__ == "__main__":
    unittest.main()
