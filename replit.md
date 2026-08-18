# Recall / Lab

## Overview

Recall / Lab is a browser-based working-memory workout inspired by the supplied Python memory-test script. It runs five timed word-sequence rounds in English or French, scores positional recall, and finishes with a reaction-time test. Completed anonymous participant results, including an age range, are stored in PostgreSQL and shown on a shared public results board with generated User labels.

## Running locally

```bash
python server.py
```

The app is served on port 5000.

## User preferences

- Keep the experience lightweight and usable without package installation.
- Prefer a calm, focused interface with clear timed states.
- Treat participant results as public data because the shared board is intentionally visible to all users.
- Never collect or display participant names; use generated User labels instead.