#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["ruamel.yaml==0.19.0"]
# ///

"""k0s Tailscale IP updater - pure transformation core."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


class UpdateError(Exception):
    """Raised when the update operation cannot proceed."""


@dataclass(frozen=True)
class AddressChange:
    """Records a single address update."""

    hostname: str
    old_address: str
    new_address: str


def resolve_addresses(status: dict[str, Any], hostnames: list[str]) -> dict[str, str]:
    """
    Resolve Tailscale IPv4 addresses for given hostnames.

    Args:
        status: Tailscale status dict with 'Self' and 'Peer' keys
        hostnames: List of hostnames to resolve

    Returns:
        Dict mapping hostname to Tailscale IPv4 (100.64.0.0/10)

    Raises:
        UpdateError: If duplicate hostname aliases or reused IPs detected,
                     or if required hostname is missing or offline
    """
    # Collect all nodes (Self + online Peers)
    nodes = []

    # Self is always online
    self_node = status.get("Self")
    if self_node:
        nodes.append(self_node)

    # Only include online peers
    peers = status.get("Peer", {})
    for peer in peers.values():
        if peer.get("Online", False):
            nodes.append(peer)

    # Build hostname->IP mapping and detect duplicates
    hostname_to_ip: dict[str, str] = {}
    ip_to_hostnames: dict[str, list[str]] = {}

    for node in nodes:
        # Extract hostname from HostName field
        hostname = node.get("HostName", "")

        # Extract first label from DNSName (e.g., "control-plane-01.example.ts.net." -> "control-plane-01")
        dns_name = node.get("DNSName", "")
        dns_first_label = dns_name.split(".")[0] if dns_name else ""

        # Get the single IPv4 in 100.64.0.0/10 range
        tailscale_ips = node.get("TailscaleIPs", [])
        ipv4_addresses = [
            ip
            for ip in tailscale_ips
            if "." in ip and ip.startswith("100.")  # Simple check for 100.64.0.0/10
        ]

        if not ipv4_addresses:
            continue

        if len(ipv4_addresses) != 1:
            raise UpdateError(f"Expected exactly one Tailscale IPv4 for {hostname}, got {len(ipv4_addresses)}")

        ip = ipv4_addresses[0]

        # Check for more precise 100.64.0.0/10 range
        octets = ip.split(".")
        if len(octets) == 4:
            try:
                first_octet = int(octets[0])
                second_octet = int(octets[1])
                # 100.64.0.0/10 means 100.64-127.*.*
                if not (first_octet == 100 and 64 <= second_octet <= 127):
                    continue
            except ValueError:
                continue
        else:
            continue

        # Register both HostName and DNS first label as aliases
        for alias in [hostname, dns_first_label]:
            if not alias:
                continue

            if alias in hostname_to_ip:
                if hostname_to_ip[alias] != ip:
                    raise UpdateError(f"Duplicate hostname '{alias}' with different IPs")
            else:
                hostname_to_ip[alias] = ip

            # Track IP reuse
            if ip not in ip_to_hostnames:
                ip_to_hostnames[ip] = []
            if alias not in ip_to_hostnames[ip]:
                ip_to_hostnames[ip].append(alias)

    # Check for reused IPs (same IP for different configured hostnames)
    # Build reverse mapping: IP -> list of configured hostnames that resolve to it
    ip_to_configured_hosts: dict[str, list[str]] = {}
    for hostname in hostnames:
        if hostname in hostname_to_ip:
            ip = hostname_to_ip[hostname]
            if ip not in ip_to_configured_hosts:
                ip_to_configured_hosts[ip] = []
            ip_to_configured_hosts[ip].append(hostname)

    # Reject if any IP is used by multiple configured hostnames
    for ip, configured_hosts in ip_to_configured_hosts.items():
        if len(configured_hosts) > 1:
            hosts_str = ", ".join(sorted(configured_hosts))
            raise UpdateError(f"Reused address {ip} for multiple configured hosts: {hosts_str}")

    # Verify all requested hostnames are available
    result = {}
    for hostname in hostnames:
        if hostname not in hostname_to_ip:
            raise UpdateError(f"Hostname '{hostname}' not found in Tailscale status or is offline")
        result[hostname] = hostname_to_ip[hostname]

    return result


def update_document(document: dict[str, Any], addresses: dict[str, str]) -> list[AddressChange]:
    """
    Update k0sctl document with new Tailscale addresses.

    Args:
        document: Parsed k0sctl YAML document (will be mutated)
        addresses: Dict mapping hostname to new IP address

    Returns:
        List of AddressChange records

    Raises:
        UpdateError: If document structure is invalid or validation fails
    """
    # Phase 1: Validation (no mutations)

    # Validate basic document structure
    if "spec" not in document or "hosts" not in document["spec"]:
        raise UpdateError("Invalid document: missing spec.hosts")

    hosts = document["spec"]["hosts"]
    if not isinstance(hosts, list):
        raise UpdateError("Invalid document: spec.hosts must be a list")

    # Validate hosts
    seen_hostnames = set()
    controllers = []
    host_validation = []

    for idx, host in enumerate(hosts):
        if not isinstance(host, dict):
            raise UpdateError(f"Invalid document: hosts[{idx}] must be a dict")

        hostname = host.get("hostname")
        if not hostname:
            raise UpdateError(f"Invalid document: hosts[{idx}] missing hostname")

        if hostname in seen_hostnames:
            raise UpdateError(f"Invalid document: duplicate hostname '{hostname}'")
        seen_hostnames.add(hostname)

        # Check if we have an address for this host
        if hostname not in addresses:
            raise UpdateError(f"No address mapping for hostname '{hostname}'")

        # Validate structure
        if "privateAddress" not in host:
            raise UpdateError(f"Invalid document: hosts[{idx}] missing privateAddress")

        if "ssh" not in host or not isinstance(host["ssh"], dict):
            raise UpdateError(f"Invalid document: hosts[{idx}] missing or invalid ssh config")

        if "address" not in host["ssh"]:
            raise UpdateError(f"Invalid document: hosts[{idx}].ssh missing address")

        old_address = host["privateAddress"]
        role = host.get("role", "")

        host_validation.append(
            {
                "idx": idx,
                "hostname": hostname,
                "old_address": old_address,
                "role": role,
            }
        )

        if role == "controller":
            controllers.append({"hostname": hostname, "old_address": old_address})

    # Validate SANs for controllers
    try:
        sans = document["spec"]["k0s"]["config"]["spec"]["api"]["sans"]
    except (KeyError, TypeError):
        raise UpdateError("Invalid document: missing spec.k0s.config.spec.api.sans")

    if not isinstance(sans, list):
        raise UpdateError("Invalid document: spec.k0s.config.spec.api.sans must be a list")

    # Verify each controller's old IP appears exactly once in SANs
    for controller in controllers:
        old_ip = controller["old_address"]
        count = sans.count(old_ip)
        if count != 1:
            raise UpdateError(
                f"Controller {controller['hostname']} old IP {old_ip} must appear exactly once in SANs, found {count}"
            )

    # Phase 2: Mutation (all validations passed)
    changes = []

    # Update SANs: replace old controller IPs with new ones (mutate in place to preserve CommentedSeq metadata)
    for controller in controllers:
        old_ip = controller["old_address"]
        new_ip = addresses[controller["hostname"]]
        # We already validated each old_ip appears exactly once, so index() is safe
        idx = sans.index(old_ip)
        sans[idx] = new_ip

    # Update each host's addresses
    for host_info in host_validation:
        idx = host_info["idx"]
        hostname = host_info["hostname"]
        old_address = host_info["old_address"]
        new_address = addresses[hostname]

        host = hosts[idx]
        host["privateAddress"] = new_address
        host["ssh"]["address"] = new_address

        changes.append(AddressChange(hostname=hostname, old_address=old_address, new_address=new_address))

    return changes


def load_status() -> dict[str, Any]:
    """
    Load Tailscale status via subprocess.

    Returns:
        Parsed JSON status dict

    Raises:
        UpdateError: If tailscale command fails, times out, or returns invalid JSON
    """
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "TAILSCALE_BE_CLI": "1"},
        )
    except FileNotFoundError:
        raise UpdateError("tailscale command not found")
    except subprocess.TimeoutExpired:
        raise UpdateError("tailscale command timed out after 15 seconds")
    except subprocess.CalledProcessError as e:
        raise UpdateError(f"tailscale command failed with exit code {e.returncode}")

    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise UpdateError(f"Invalid JSON from tailscale: {e}")

    if not isinstance(status, dict):
        raise UpdateError("Expected JSON object from tailscale status")

    return status


def update_file(config_path: Path, status: dict[str, Any], dry_run: bool = False) -> list[AddressChange]:
    """
    Update k0sctl config file with Tailscale addresses.

    Args:
        config_path: Path to k0sctl YAML config
        status: Tailscale status dict
        dry_run: If True, validate and return changes without writing

    Returns:
        List of AddressChange records

    Raises:
        UpdateError: If validation fails or I/O error occurs
    """
    # Load YAML with quote preservation
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            document = yaml.load(f)
    except FileNotFoundError:
        raise UpdateError(f"Config file not found: {config_path}")
    except Exception as e:
        raise UpdateError(f"Failed to load config: {e}")

    # Extract all hostnames from document
    try:
        hosts = document["spec"]["hosts"]
        hostnames = [host["hostname"] for host in hosts]
    except (KeyError, TypeError, AttributeError):
        raise UpdateError("Invalid document structure")

    # Resolve addresses (validates all constraints)
    addresses = resolve_addresses(status, hostnames)

    # Update document in-memory (validates document structure)
    changes = update_document(document, addresses)

    # Return early for dry run
    if dry_run:
        return changes

    # Atomic write: temp file -> fsync -> replace
    original_mode = config_path.stat().st_mode

    temp_fd = None
    temp_path = None
    try:
        # Create temp file in same directory to ensure atomic rename
        temp_fd, temp_name = tempfile.mkstemp(
            dir=config_path.parent, prefix=".k0s-", suffix=".yaml.tmp"
        )
        temp_path = Path(temp_name)

        # Write to temp file
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            temp_fd = None  # fdopen takes ownership
            yaml.dump(document, f)
            f.flush()
            os.fsync(f.fileno())

        # Restore original permissions
        temp_path.chmod(original_mode)

        # Atomic replace
        os.replace(temp_path, config_path)
        temp_path = None  # Successfully renamed

    except Exception as e:
        raise UpdateError(f"Failed to write config: {e}")
    finally:
        # Clean up temp file if it still exists
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except Exception:
                pass
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

    return changes


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code: 0 for success, 1 for error
    """
    parser = argparse.ArgumentParser(
        description="Update k0sctl config with Tailscale addresses"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent.parent / "docs" / "k0s" / "k0s.yaml",
        help="k0sctl config (default: <repo>/docs/k0s/k0s.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned changes without writing",
    )

    args = parser.parse_args(argv)

    try:
        status = load_status()
        changes = update_file(args.config, status, dry_run=args.dry_run)

        # Print changes
        for change in changes:
            print(f"{change.hostname}: {change.old_address} -> {change.new_address}")

        # Print summary
        if args.dry_run:
            print("Dry run: no files written")
        elif changes:
            print(f"Updated {args.config}")
        else:
            print("No address changes")

        return 0

    except UpdateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

