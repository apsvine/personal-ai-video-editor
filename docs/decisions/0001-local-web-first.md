# ADR 0001: Start as a local web application

Status: Accepted direction; implementation deferred beyond Phase 00.

## Context

This is a private, local-first editor for one user. Its initial uncertainty is
the reliability of the media-to-edit pipeline, not desktop distribution.

## Decision

Begin with a local React + TypeScript web interface and Python + FastAPI
backend in future phases. Add Electron packaging only after the pipeline is
stable. Keep planner, media operations, and renderer behind clear boundaries.

## Consequences

Pipeline components can be tested independently without desktop packaging
complexity. Initial use will require a browser and local services; installers,
desktop lifecycle, updates, and OS integration remain future work. Local web
does not mean hosted/cloud processing or public network exposure.
