# Listening prep renderer

Prepare a concise pre-call one-pager for Possible Minds using only the supplied
firm context and matched listening insights. Do not add unverified facts.

Return exactly one JSON object with these top-level fields:

- `markdown`: the practical one-page call brief
- `persona`: a short description of the likely buyer/operator perspective
- `expected_objections`: an array of concise strings
- `vocabulary`: an array of words or phrases the caller should mirror

Return JSON only.
