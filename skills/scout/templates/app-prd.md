---
type: application
name: Product Requirements Document
output_suffix: prd
---

## Problem Statement
<!-- essential -->
What problem does this application solve? Who has this problem and how do
they currently deal with it?

## Target Audience
<!-- essential -->
Primary and secondary users. Their technical sophistication, usage context,
and what success looks like for them.

## User Personas
<!-- optional -->
Named archetypes with goals, frustrations, and usage patterns. Only include
if the audience segments are meaningfully different.

## Requirements
<!-- essential -->
Functional requirements grouped by feature area. Each requirement should be
specific and testable. Use "must", "should", "could" priority levels.

## Architecture
<!-- essential -->
High-level system design. Components, their responsibilities, and how they
communicate. Include deployment model (local, cloud, hybrid).

## Data Model
<!-- optional -->
Key entities, their relationships, and storage approach. Include any
external data sources or integrations.

## API Surface
<!-- optional -->
Public interfaces — REST endpoints, CLI commands, SDK methods, or IPC
protocols. Include request/response shapes for critical paths.

## Security & Auth
<!-- optional -->
Authentication method, authorization model, data protection requirements.
Compliance constraints if any.

## Success Metrics
<!-- optional -->
How you'll know this is working. Quantitative metrics preferred.

## Technical Constraints
<!-- optional -->
Language/framework requirements, platform targets, performance budgets,
dependency restrictions.

## Roadmap
<!-- essential -->
Version milestones with scope. Each version should deliver usable
functionality. Format: `vX.Y — milestone name — brief scope description`.
