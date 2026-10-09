# Architecture diagrams

Each diagram has an editable **Excalidraw source** and an **SVG preview** that renders directly in the runbooks. The SVG also embeds its Excalidraw scene. Click a preview for full-size viewing; download either format to open it in [Excalidraw](https://excalidraw.com).

Read flow rows left to right. Numbered sections run from top to bottom. Topology and ownership sections describe placement or responsibility rather than packet hops. Blue marks clients and hosts, purple marks networking and controllers, green marks workloads and data, orange marks external services, and yellow marks credentials or operational constraints. Every meaning is also written in text.

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
2. Edit the native shapes, labels and connected arrows. Keep the runbook and checked-in configuration as the architecture reference.
3. Save the `.excalidraw` file over the matching source in this repository.
4. Export the entire scene as SVG. Enable **Background** and **Embed scene**, use a white background and light mode, and replace the matching `.svg` file.
5. Inspect the SVG at roughly 800–1000 pixels wide. Check text wrapping, arrow endpoints, separation between flows, and sufficient contrast. Open it back in Excalidraw to confirm it remains editable.
6. Run `git diff --check` and review both files together.

Use Excalidraw's **Nunito** font for labels and body text (22 pixels), sentence-case section headings (24 pixels), and **Lilita One** for diagram titles (36 pixels). Keep text dark against the light fills. The SVG export embeds the fonts so previews remain consistent across machines.

Left-align box text with 24 pixels of padding and align the first lines across each row. Separate a component name from its details with a blank line. Wrap at word boundaries, keeping resource names intact; move long identifiers into a nearby note when necessary. Size boxes to fit the text and give all boxes in a row the same height. Put a section's explanation below its heading, and leave at least 24 pixels between text, boxes, and adjacent sections.

Use straight, solid indigo arrows with filled triangle heads, a 2.5-pixel stroke, and no sloppiness. Bind both ends to their shapes and leave a visible gap at each endpoint. Put distinct flows in separate rows rather than crossing connectors. Use generous spacing and short labels; keep detailed commands and troubleshooting in the runbook. Retain only the source and SVG; temporary review screenshots do not belong in Git.
