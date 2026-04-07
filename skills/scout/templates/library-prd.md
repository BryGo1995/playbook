---
type: library
name: Library/Tool Requirements Document
output_suffix: prd
---

## Purpose
<!-- essential -->
What does this library/tool do? One paragraph covering the problem space,
why existing solutions are insufficient, and what this provides.

## Target Users
<!-- essential -->
Who will use this? Developers, ops teams, end users? What's their skill
level and what ecosystem do they work in?

## API Design
<!-- essential -->
The public interface. For each major function/class/command:
- Signature and parameters
- Return value and side effects
- Usage example

Design for the consumer's ergonomics, not the implementation's convenience.

## Use Cases
<!-- essential -->
Concrete scenarios showing how the library/tool is used end-to-end.
Include the "happy path" and at least one edge case per use case.

## Integration Patterns
<!-- optional -->
How does this fit into a larger system? Import/install method, configuration,
and common composition patterns with other tools.

## Compatibility
<!-- optional -->
Language/runtime versions, OS support, browser targets, dependency
constraints. Breaking change policy.

## Performance Constraints
<!-- optional -->
Latency budgets, memory limits, throughput targets. Benchmarking approach.

## CLI Interface
<!-- optional -->
If the tool has a CLI: commands, flags, output formats. Include examples
of common invocations.

## Error Handling
<!-- optional -->
Error taxonomy, reporting approach (exceptions, result types, exit codes),
and recovery guidance for consumers.

## Roadmap
<!-- essential -->
Version milestones with scope. Each version should be independently
publishable. Format: `vX.Y — milestone name — brief scope description`.
