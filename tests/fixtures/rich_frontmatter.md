---
title: Architecture Decision Record — Event Sourcing
authors:
  - Thomas Rohde
  - Jane Doe
tags:
  - architecture
  - event-sourcing
  - cqrs
category: ADR
priority: high
created: 2026-03-10
updated: 2026-04-15
reviewed: true
links:
  jira: PROJ-1234
  confluence: https://wiki.example.com/adr/007
---

# ADR-007: Adopt Event Sourcing for Order Domain

## Context

The order service currently uses a traditional CRUD model with a single
`orders` table. This causes problems when auditing state transitions and
replaying failed workflows.

## Decision

We will adopt event sourcing for the order aggregate. Commands produce
domain events; the current state is derived by folding the event stream.

### Pros

- Full audit trail for free
- Temporal queries ("what was the order at 14:00?")
- Natural fit for async consumers (shipping, billing)

### Cons

- Higher storage cost
- Eventually-consistent read models
- Team needs training

## Consequences

| Area          | Impact    |
|---------------|-----------|
| Storage       | +40 %     |
| Read latency  | +5 ms p99 |
| Auditability  | Complete  |

## Status

Accepted — implementation begins sprint 12.
