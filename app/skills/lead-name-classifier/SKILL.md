---
name: lead-name-classifier
description: Single-shot classifier. Given one lead's name/firm/title, decide whether the "name" field is a real human person or a firm/brand. Returns strict JSON {"is_person": bool}. Called by app/cli.py (leads backfill-names) via the OpenClaw proxy gateway; not an interactive runbook.
---

# Lead name classifier (single-shot)

You classify whether a lead's `name` field is a real human person or a
firm/brand/placeholder. Return **only** a JSON object — no prose, no markdown
fences.

## Input
```json
{ "name": "Sweet James", "firm_name": "Sweet James Accident Attorneys", "title": "" }
```

## Output (STRICT JSON, this exact shape)
```json
{ "is_person": false }
```

## Rules
- `is_person=true` when `name` is a real human name (e.g. "Erika Almeida",
  "Jim Adler").
- `is_person=false` when `name` is a firm name, brand, initials, or non-person
  placeholder (e.g. "Sweet James", "Banner Law Group", "JP Law", "The Hammer").
- When uncertain, prefer `true` only if it reads as a plausible first+last human
  name; otherwise `false`.
- Always output the `is_person` key.
