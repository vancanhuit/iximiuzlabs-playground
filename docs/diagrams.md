# Architecture diagrams

Each diagram has an editable Excalidraw source and an SVG preview with the scene embedded. Click a preview to view it at full size. Download either format to edit it in [Excalidraw](https://excalidraw.com).

Read flow rows from left to right, then continue below. Numbers identify ordered steps or authorization checks. Placement and provisioning sections describe where components run and which controller owns them.

The Kubernetes and SOPS diagrams use these component roles and colors. Labels carry the same meaning without relying on color:

| Role | Fill | Border |
| --- | --- | --- |
| Clients and hosts | Blue `#eff6ff` | `#2563eb` |
| Networking and controllers | Purple `#f5f3ff` | `#7c3aed` |
| Workloads and data | Green `#ecfdf5` | `#15803d` |
| External services | Orange `#fff7ed` | `#c2410c` |
| Credentials and constraints | Yellow `#fffbeb` | `#a16207` |
| Provisioning notes | Gray `#f8fafc` | `#64748b` |

## Kubernetes and secrets

| Diagram | Preview | Editable source |
| --- | --- | --- |
| Cluster topology and access | [SVG](k0s/architecture/lab-architecture.svg) | [Excalidraw](k0s/architecture/lab-architecture.excalidraw) |
| Bootstrap order | [SVG](k0s/architecture/bootstrap-journey.svg) | [Excalidraw](k0s/architecture/bootstrap-journey.excalidraw) |
| Node, Pod, Service and egress paths | [SVG](k0s/architecture/network-data-paths.svg) | [Excalidraw](k0s/architecture/network-data-paths.excalidraw) |
| Tailscale identity and Kubernetes RBAC | [SVG](k0s/architecture/api-impersonation.svg) | [Excalidraw](k0s/architecture/api-impersonation.excalidraw) |
| Hubble private HTTPS | [SVG](k0s/architecture/hubble-private-https.svg) | [Excalidraw](k0s/architecture/hubble-private-https.excalidraw) |
| Hubble DNS-01 certificate issuance | [SVG](k0s/architecture/hubble-dns01.svg) | [Excalidraw](k0s/architecture/hubble-dns01.excalidraw) |
| Echo Gateway API | [SVG](k0s/architecture/echo-gateway-api.svg) | [Excalidraw](k0s/architecture/echo-gateway-api.excalidraw) |
| Monitoring Gateway API | [SVG](k0s/architecture/monitoring-gateway-api.svg) | [Excalidraw](k0s/architecture/monitoring-gateway-api.excalidraw) |
| SOPS and age | [SVG](k0s/architecture/sops-age.svg) | [Excalidraw](k0s/architecture/sops-age.excalidraw) |

## Incus

| Diagram | Preview | Editable source |
| --- | --- | --- |
| Cluster, management and local storage | [SVG](incus/architecture/incus-cluster.svg) | [Excalidraw](incus/architecture/incus-cluster.excalidraw) |
| OVN traffic and recovery paths | [SVG](incus/architecture/ovn-network.svg) | [Excalidraw](incus/architecture/ovn-network.excalidraw) |

## Edit a diagram

1. Download the `.excalidraw` file and open it with Excalidraw's **Open** action, or drag it onto the canvas. An SVG with an embedded scene works too.
2. Edit the native shapes, labels and connected arrows. Keep each card's heading and body text grouped with its box. Use the runbook and checked-in configuration as the architecture reference.
3. Save the `.excalidraw` file over the matching source in this repository.
4. Export the entire scene as SVG. Enable **Background** and **Embed scene**, use a white background and light mode, and replace the matching `.svg` file.
5. Inspect the SVG at roughly 800 to 1000 pixels wide. Check text wrapping, arrow endpoints, separation between flows, and sufficient contrast. Open it back in Excalidraw to confirm it remains editable.
6. Run `git diff --check` and review both files together.

Use Nunito for body text (22 pixels), card headings (24 pixels), and section headings (24 pixels). Use Lilita One for diagram titles (36 pixels). Keep headings in sentence case. Use dark `#172033` headings, `#334155` card text, and `#475569` descriptions against light fills. Embed the fonts in the SVG export.

Left-align card text with 24 pixels of padding and a 12-pixel gap between the heading and body. Align the first lines and match card heights within each row. Wrap at word boundaries; keep resource names intact or move them into a nearby note. Put section descriptions below their headings. Leave at least 24 pixels before a row of cards and 34 pixels before the next section. Use light fills, 1.5-pixel borders, and a 12-pixel corner radius.

Use straight, solid indigo arrows with filled triangle heads, a 2.5-pixel stroke, and no sloppiness. Bind both ends to their shapes and leave a visible gap at each endpoint. Put distinct flows in separate rows rather than crossing connectors. Use generous spacing and short labels; keep detailed commands and troubleshooting in the runbook. Retain only the source and SVG; temporary review screenshots do not belong in Git.
