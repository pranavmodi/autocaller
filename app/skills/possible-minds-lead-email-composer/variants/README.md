# Lead Email Composer Variants

Drop A/B test skill variants here:

```text
variants/
  my-variant/
    SKILL.md
    variant.json
```

`SKILL.md` must follow the same JSON output contract as the baseline composer.

`variant.json` is optional:

```json
{
  "key": "my-variant",
  "label": "My Variant",
  "description": "What this skill is testing.",
  "allocation_weight": 100,
  "active": true
}
```

The baseline skill at `../SKILL.md` is always included as variant `baseline`.
Active variants are assigned deterministically per contact using rendezvous
hashing, so a contact stays on the same variant within the experiment.
