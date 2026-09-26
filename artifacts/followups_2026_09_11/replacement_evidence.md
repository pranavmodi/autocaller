# Sep 11 follow-up replacement evidence

Status: selected, pre-mutation. Generated 2026-09-11 01:17:50 PDT.

The corrected query ranks all email history first, so `actual_latest_at` and `lifetime_send_count` are lifetime values rather than values from a prefiltered window. Each selected person has exactly two lifetime sends, with the actual latest delivered touch on Aug 31. All five have zero stored inbound replies, zero bad deliveries, zero negative or opt-out outcomes, and zero future pending actions.

Each latest touch was a successful follow-up action whose stored `in_reply_to` and `references` contain a real previously validated RFC ancestor. The planned next reply will preserve the same subject and use that ancestor. The five contacts, PIF records, primary email domains, and recipient identities are distinct.

| Contact | Firm | Role | Latest UTC | Lifetime sends | Source action | RFC ancestor |
| --- | --- | --- | --- | ---: | --- | --- |
| Neal Kuvara | Kuvara Law Firm | Founder | 2026-08-31 17:40:29 | 2 | `action_f01b442b551e4e30ae24e63c` | `<0100019ffc5ef974-b26b2402-ff15-4ac9-8ae5-0491b54f718d-000000@email.amazonses.com>` |
| Vadim F. Frish | Frish Law Group, APLC | Founder, Partner | 2026-08-31 17:30:29 | 2 | `action_a3fe2e7de2784435ac1a7ee4` | `<0100019ffc63903e-abd24c0a-1e89-46f0-9670-016c5d70d9e5-000000@email.amazonses.com>` |
| Ardy Pirnia | Pirnia Law Group | Founder & Principal Attorney | 2026-08-31 17:20:28 | 2 | `action_af6ea47b52a045e796926a44` | `<0100019ffc6cbc39-05787cc1-e00e-494d-8fef-fdc418c667a4-000000@email.amazonses.com>` |
| Bryan Khalilirad | Rodeo Law Firm, PC | Founder & Managing Partner | 2026-08-31 17:10:27 | 2 | `action_ffe45200c0bf4feeb8029ab2` | `<0100019ffc75e810-37621cba-fa99-491b-8c46-ee5bb84c3a2f-000000@email.amazonses.com>` |
| Nicole Lahmani, Esq. | Lahmani Law, APC | Founder & Principal | 2026-08-31 16:20:22 | 2 | `action_5fb7d8b70ee148e0b271ff1b` | `<0100019ffc9abd29-2efd626a-b336-4141-ac00-4b0ce32d12d6-000000@email.amazonses.com>` |

Next step: create one canonical Sep 11 follow-up batch, add these existing contacts, save the five individualized plaintext replies, and only then schedule via the CLI after one final live reply, bounce, outcome, pending-action, alias, scheduler, capacity, and policy check.
