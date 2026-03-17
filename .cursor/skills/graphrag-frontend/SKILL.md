---
name: graphrag-frontend
description: >
  Rules for the GraphRAG frontend, especially the Graph Explorer UI built with
  React and ForceGraph2D under apps/src/. Use this when modifying graph
  visualization or query controls in the frontend.
---

# GraphRAG Frontend (Graph Explorer) Conventions

## Scope

- `apps/src/App.jsx`
- `apps/src/pages/GraphExplorer.jsx`
- Any shared components/styles that affect the knowledge base UI.

## Backend API Contracts

Graph Explorer and related UI components must consume the following backend APIs
via the `/api` prefix in the frontend:

- `/api/graph/nodes`
- `/api/graph/relations`
- `/api/graph/subgraph?entity=<name>`
- `/api/graph/path?a=<A>&b=<B>`
- `/api/graph/node_documents?entity=<name>`

The normalized response shape for graph data is:

```json
{
  "nodes": [
    { "id": ..., "labels": [...], "properties": {...} }
  ],
  "edges": [
    { "source": ..., "target": ..., "type": "...", "properties": {...} }
  ]
}
```

The frontend should transform this into ForceGraph2D format:

```ts
{
  nodes: [{ id, name, type, raw }],
  links: [{ id, source, target, label, raw }]
}
```

## Visualization Rules

- Use **ForceGraph2D** as the primary visualization component.
- Nodes:
  - Must carry:
    - `id` (stringified graph id).
    - `name` (from `properties.name/title/file_name`).
    - `type` (first label or a derived type).
    - `raw` (full original node record for tooltips/panels).
  - `nodeLabel` should show at least name, type, and source document (if available).

- Edges:
  - Visualized as directional links with:
    - Clear color and sufficient width for visibility on dark background.
    - Optional arrowheads indicating direction.
  - `linkLabel` should display the relation `type` where useful.

## Interaction Patterns

- **Subgraph navigation**
  - Clicking a node:
    - Triggers `/api/graph/subgraph?entity=<name>` to load a 1-hop neighborhood.
    - Updates the graph view and any detail panels (e.g. document sidebar).

- **Path search**
  - UI should provide inputs for “Entity A” and “Entity B” plus a “Find path” button.
  - On submit, call `/api/graph/path` and re-render the graph with the returned path subgraph.

- **Document evidence panel**
  - When a node is selected, fetch `/api/graph/node_documents?entity=<name>` and display:
    - Document name (`file`).
    - Text snippet (`text`).

- **Reset view**
  - Provide a clear control (e.g. “Reset view”) to reload the global relations view
    from `/api/graph/relations`.

## UX Guidelines

- Keep the graph canvas full-screen within its layout region.
- Support:
  - Zoom.
  - Pan.
  - Node drag.
- Ensure the UI remains responsive even with ~200 relations:
  - Avoid unnecessary re-renders.
  - Reuse existing graph data structures when possible.

