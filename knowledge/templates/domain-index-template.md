# Index Node: [Domain / Sub-domain]

> A node in the index tree. Loaded on-demand when a task matches this scope — NOT injected at session
> start (only the root `INDEX.md` is). Created by Memory Agent when a parent node exceeds the shard
> threshold (see `agents/memory.md` → Index Health & Sharding). The parent carries a shard-pointer
> row to this file. Index nodes are navigation — they do NOT count toward the max-5 content-file
> budget. Maintained by Memory Agent.

## Topic shards (sub-nodes — fill only if this node has itself been split)

> If this node grows past the threshold (> 15 topics), split it further: move sub-clusters into
> `indexes/index_<this>_<child>.md` and list them here. A node with rows here is a map of maps.
> Leave this table empty (or omit) for a leaf node.

| Shard | Sub-domain | Tags | Load when |
|---|---|---|---|
| [indexes/index_<this>_<child>.md] | [sub-domain] | [tags] | [trigger — full map of N topics] |

## topics

> Same format and frontmatter rules as the root index's topics section.

| File | Tags | When to load |
|---|---|---|
| [topic-file.md] | [tag1, tag2, tag3] | [trigger description] |

## patterns (domain-specific, if any)

| File | Tags | When to load |
|---|---|---|
| [pattern-file.md] | [tag1, tag2] | [trigger description] |

---

When this node drops well below the shard threshold (< ~8 topics), Memory Agent proposes merging it
back into its parent during Periodic Curation — collapsing needless depth.
