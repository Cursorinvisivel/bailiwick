# indexes/ — the index tree

Home for **sharded index nodes** (`index_<path>.md`). Indexes form a recursive **tree**: the root
`../INDEX.md` is level 0, and any node that grows past the shard threshold (default: > 15 topics —
see `../../agents/memory.md` → Index Health & Sharding) pushes a sub-cluster down into a deeper node
here. A deeper node can itself split again — the tree has no fixed depth (but stay shallow; see below).

## Why this exists
The root `../INDEX.md` is injected into every wired session by the SessionStart hook, so it must stay
lean. Large domains are pushed down here as sub-maps; each node keeps only its own subtree and leaves
a one-line **shard-pointer row** in its parent.

## Naming (encodes the path from root)
```
INDEX.md                              level 0 (injected)
indexes/index_<domain>.md             level 1  (domain)
indexes/index_<domain>_<sub-a>.md      level 2  (sub-domain)
indexes/index_<domain>_<sub-b>.md      level 2
```
A node with shard-pointer rows is a **map of maps**; a node with topic rows is a **leaf**.

## How it's used
- Root INDEX (always injected) → top-level pointers + triggers.
- Descend **on-demand**: load the matching node, follow its pointer to the next level, until you reach
  the leaf with the topics you need. Deeper nodes are never injected.
- Index nodes are **navigation**: they do NOT count toward the max-5 *content*-file budget. But keep
  the descent shallow — target ≤2 levels below root, hard cap 3. More index hops than content files
  means the tree is over-split → merge.

## Maintenance
Memory Agent creates, splits, and merges nodes (human-gated) during Collect and Periodic Curation,
recounting **per node**. Use `../templates/domain-index-template.md` for any new node. Empty until the
first domain shards.
