from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.services.comms_log import _engine


BATCH_ID = "7011677f4d8c40bbaf694543685c8750"
DAY_START = "2026-09-10 07:00:00+00"
DAY_END = "2026-09-11 07:00:00+00"
PRECISE_SUBJECT = "Precise Imaging - A quick question"
EMOTION = (
    "The more firm owners I speak with, the more convinced I am that the best AI "
    "opportunities are often the unglamorous handoffs and follow-ups that quietly "
    "consume a team's day."
)
APPRECIATION_PREFIX = "I'd really value your instinct, even if it's only a line: "
VERIFIED_PRECISE_PIF_IDS = {
    "3d7777c1-b309-4c4e-81f6-e0c32ebc2f6a",  # Ayala, Morgan & Buzzard
    "00edf762-38e6-4c15-a068-31c4669fb6d9",  # CHICHYAN LAW APC
    "4c7a9396-e525-42a7-86a0-259f81871baa",  # Howell Law Firm PC
    "31e5c8ee-08ed-48a0-9718-2c0eae80e02d",  # Jared J. Drucker Law
    "1f779e35-34b7-468d-a80e-90ebea71bcb5",  # Joe Naz Law
    "08c30619-01bd-496c-9f5f-f959a1ee2974",  # LA Injury Law Group
    "41903a64-65f1-4a95-9fb5-27ece61c771a",  # Law Offices of Morteza Aghavali
    "473e05b3-9fac-4ea6-add5-f560edb8fba8",  # MESSRELIAN Law Inc.
    "502eb6b1-a638-492d-9451-ec360d2fe062",  # Pheffer Law
    "1621a962-7288-4596-afc9-3e3fd22332f9",  # Piering Law Firm
    "26b87673-0ad8-4050-bd73-e35bea112fc7",  # Premier Justice Law, P.C.
    "593a038b-21a7-4f37-8e8e-217dd50be4f2",  # Richard Harris Law Firm
    "1175d38e-7fe1-474f-b59b-82b0c524f4ed",  # Taherian Injury Law, PC
    "3014b0f2-d86d-4a75-86b8-f991993e771a",  # The Law Giant
    "c0580151-08d0-4c62-9bac-6903cd775851",  # The Rezvani Law Firm
}

HOOK_OVERRIDES = {
    "593a038b-21a7-4f37-8e8e-217dd50be4f2": (
        "As managing partner of a broad PI practice, you've probably seen how easily "
        "a callback can lose context as it moves between people and Litify. That "
        "makes your view of the issue in my earlier note especially useful."
    ),
    "c0580151-08d0-4c62-9bac-6903cd775851": (
        "As founder and managing partner, you probably see where Filevine keeps "
        "callbacks visible and where staff still has to connect an update to the "
        "right matter. That makes your view of the review in my earlier note "
        "especially useful."
    ),
    "3d7777c1-b309-4c4e-81f6-e0c32ebc2f6a": (
        "As a founding partner handling everything from truck crashes to brain "
        "injuries and wrongful-death matters, you've probably seen how differently "
        "information moves through each kind of case. That makes your perspective "
        "especially useful here."
    ),
    "218c3abc-dc1c-4fed-9435-72d369e81241": (
        "After building California Attorney Group since 2004 and resolving more than "
        "$250 million for clients, you've seen how small handoff gaps can turn into "
        "a lot of invisible staff work. That experience gives you a useful view of "
        "where AI can help without disrupting what already works."
    ),
    "4c7a9396-e525-42a7-86a0-259f81871baa": (
        "Because you emphasize direct attorney involvement across personal-injury "
        "and employment matters, you've had to balance responsiveness with keeping "
        "the experience personal. That makes your judgment on where automation "
        "belongs especially useful."
    ),
    "502eb6b1-a638-492d-9451-ec360d2fe062": (
        "As the owner of a practice using a custom system like FileMaker, you've "
        "probably seen both the value of fitting technology to the firm and the "
        "friction of adding the next layer. That makes your perspective on practical "
        "AI especially useful."
    ),
    "457a9dbb-6116-4db7-95e7-c99ef62be15b": (
        "As the founder handling serious-injury and wrongful-death matters, you've "
        "had to give clients clarity while the medical and legal record is still "
        "changing. That makes your perspective on client-facing AI especially useful."
    ),
    "132f3bb3-37dc-4673-9b80-17ee3b81f3df": (
        "By putting client service at the center of your PI practice, you've set a "
        "high bar for any automation: it has to improve responsiveness without "
        "making communication feel impersonal. That makes your judgment especially "
        "useful."
    ),
    "1175d38e-7fe1-474f-b59b-82b0c524f4ed": (
        "As you build Taherian Injury Law around personal-injury work, you have a "
        "rare chance to design the operating model before manual habits become "
        "permanent. That makes your perspective on bringing AI in early especially "
        "valuable."
    ),
    "4d964135-d2fb-4be2-856e-a6c1ba6df811": (
        "As a founding partner, you've seen personal-injury workflows change as both "
        "the matters and the team become more complex. That long view makes your "
        "perspective on practical AI especially useful."
    ),
    "00f86ff9-8196-4518-bf3d-6b41ff5cbf2d": (
        "After more than 40 years in litigation, including insurance-defense work, "
        "you've seen claim operations from both sides. That perspective is unusually "
        "useful when deciding where AI can help and where human judgment still matters."
    ),
    # The stored Litify evidence for SHK is not strong enough to name the vendor.
    "0bd3a904-a6c0-439e-b061-b4e6adc0918f": (
        "As co-founder and managing partner across a wide range of injury matters, "
        "you've probably seen which handoffs travel well across case types and which "
        "still depend on staff memory. That makes your operational perspective "
        "especially useful."
    ),
    "3014b0f2-d86d-4a75-86b8-f991993e771a": (
        "As founding shareholder of a practice spanning Texas and New Mexico, you've "
        "had to make intake and information routing work across markets and matters "
        "ranging from individual claims to mass torts. That gives you a useful view "
        "of where AI could actually help."
    ),
    "1c6ecc4c-059e-41f1-8b6f-b1ac0d7189e1": (
        "As founder and lead attorney across everything from vehicle claims to "
        "watercraft accidents and burn injuries, you've probably seen how differently "
        "providers, records, and follow-ups move from case to case. That makes your "
        "perspective especially useful."
    ),
    "472f056d-ab01-4be9-9b4f-e4983f502400": (
        "As co-founder of a firm handling both accident and catastrophic-injury "
        "matters in Filevine, you've probably seen where the case system ends and "
        "manual work begins. That makes your view of the next useful AI layer "
        "especially valuable."
    ),
    "1621a962-7288-4596-afc9-3e3fd22332f9": (
        "As founder and managing partner handling accident, elder-abuse, and "
        "auto-product matters, you've seen case types with very different evidence "
        "and follow-up paths. That makes your perspective on recurring handoffs "
        "especially useful."
    ),
    "4681046b-ddd0-43ad-9fb7-657cffadbc46": (
        "As founder and managing attorney serving injury clients across Southern "
        "California, you've had to keep workflows consistent across matters ranging "
        "from vehicle crashes to brain injuries and wrongful death. That makes your "
        "perspective especially useful."
    ),
    "0976163e-ecf3-40e9-9909-38dc59adf6d0": (
        "As founder and principal attorney across both personal-injury and "
        "product-liability work, you've seen the information burden change even when "
        "clients face similar pressure points. That makes your perspective on "
        "practical AI especially useful."
    ),
    "1d771571-c7b5-4a87-b0c9-826c85c1ed4e": (
        "As founder and principal attorney across personal injury, civil rights, and "
        "employment matters, you've had to make Filevine support very different "
        "intake and follow-up paths. That makes your perspective on where AI fits "
        "especially useful."
    ),
    "08c30619-01bd-496c-9f5f-f959a1ee2974": (
        "As a founding partner handling accident and product-liability matters in "
        "Filevine, you've probably seen how much important follow-up still happens "
        "around the case system. That makes your perspective on the next automation "
        "layer especially useful."
    ),
    "070e8271-921e-418d-a559-039e682cde77": (
        "As founder and lead attorney across vehicle, brain, spinal, burn, and "
        "workplace injury matters, you've seen how dramatically the medical-documentation "
        "burden can change from one case to the next. That makes your perspective "
        "especially useful."
    ),
    "207f726c-b6d6-4a25-ba57-f01843608c72": (
        "As founder and owner handling accident, premises, and wrongful-death matters "
        "in MyCase, you've probably seen what stays organized in the platform and "
        "what still lives in email or staff memory. That makes your perspective "
        "especially useful."
    ),
    "31e5c8ee-08ed-48a0-9718-2c0eae80e02d": (
        "As founder and attorney handling both everyday accident claims and "
        "catastrophic-injury or medical-malpractice matters, you've seen how "
        "differently intake, records, and client communication can unfold. That makes "
        "your perspective especially useful."
    ),
    "32810ceb-79a0-446f-9cd4-eff8abbfc86b": (
        "As founding partner across injury, professional-negligence, and insurance "
        "disputes, you've seen different facts create the same pressure to keep every "
        "update and document tied to the right matter. That gives you a useful view "
        "of where AI can help."
    ),
    "019a7b9c-a586-4875-8313-ca14f084ef92": (
        "As owner of a practice spanning personal injury, criminal defense, and "
        "juvenile defense, you've had to support very different intake questions and "
        "follow-up rhythms under one roof. That makes your perspective on practical "
        "AI especially useful."
    ),
    "18b41dc0-eabb-4c7e-b2cc-de25bee2f2b3": (
        "As founder handling accident claims alongside medical and pharmacist "
        "malpractice, you've seen how medical-heavy matters can turn records "
        "collection and status follow-up into substantial operational work. That "
        "makes your perspective especially useful."
    ),
    "33a642da-1bd5-4b6d-8c42-9fb3b43afbdc": (
        "As founder working across workers' compensation, employment, and personal "
        "injury, you've had to respect very different intake and documentation paths "
        "rather than force one process across every matter. That makes your "
        "perspective especially useful."
    ),
    "00edf762-38e6-4c15-a068-31c4669fb6d9": (
        "As founder and lead attorney across cases ranging from vehicle collisions to "
        "brain injuries and wrongful death, you've probably seen how differently "
        "records, updates, and staff handoffs unfold. That makes your perspective "
        "especially useful."
    ),
    "065ec091-1c29-4d80-ae55-dc51a179bc94": (
        "As owner and principal attorney across criminal, family, and personal-injury "
        "matters, you've had to decide which very different workflows belong in "
        "Smokeball and which still need work around it. That makes your perspective "
        "especially useful."
    ),
    "26571076-a7e7-4c05-9472-f3be8ebd48d0": (
        "As a founder and senior attorney handling product-liability and mass-tort "
        "work alongside individual injury claims, you've seen how even small "
        "document-routing delays can multiply. That makes your perspective on "
        "practical AI especially useful."
    ),
    "296d48f4-24be-4265-b111-73f8cd2eb030": (
        "As principal of a practice handling rideshare, truck, pedestrian, premises, "
        "and wrongful-death matters, you've probably seen each case create a different "
        "chain of providers and follow-ups. That makes your perspective especially "
        "useful."
    ),
    "500a260a-c1f9-4c4d-ada5-c0394d2faeb4": (
        "As co-founder across workers' compensation, personal injury, and employment "
        "matters, you've had to standardize intake and client updates without "
        "flattening important differences. That makes your perspective on where AI "
        "fits especially useful."
    ),
    "1f779e35-34b7-468d-a80e-90ebea71bcb5": (
        "As founder and managing attorney handling both accident and "
        "catastrophic-injury matters in CASEpeer, you've probably seen where the case "
        "system ends and manual work begins. That makes your perspective on the next "
        "practical AI layer especially useful."
    ),
    "2f4a3bbd-7305-4d4a-97d0-30fd7e309d6b": (
        "As founding partner across lemon-law and personal-injury matters, you've had "
        "to manage very different evidence and communication cycles while keeping "
        "intake and follow-up consistent. That makes your perspective especially useful."
    ),
    "3b585488-015c-4e31-9f8b-56bc66791d31": (
        "As founder and lead attorney across auto, bicycle, truck, and train collision "
        "matters, you've probably seen provider coordination and records follow-up "
        "change substantially from case to case. That makes your perspective "
        "especially useful."
    ),
    "41903a64-65f1-4a95-9fb5-27ece61c771a": (
        "As principal of a practice combining personal injury, medical malpractice, "
        "and health-care matters, you've seen records, providers, and expert "
        "follow-up move at very different speeds. That makes your perspective "
        "especially useful."
    ),
    "473e05b3-9fac-4ea6-add5-f560edb8fba8": (
        "As founder and managing attorney across personal injury, employment, "
        "criminal defense, and fire-damage claims, you've had to support very "
        "different intake paths and follow-up expectations within one practice. That "
        "makes your perspective especially useful."
    ),
    "0253c2ff-d342-49be-acb1-f0e6a5481344": (
        "As founder and managing partner across everyday accident claims, catastrophic "
        "injuries, and insurance disputes, you've probably seen how difficult it is "
        "to keep records and communication workflows consistent. That makes your "
        "perspective especially useful."
    ),
    "2a94cadc-0009-4565-8089-4adae3d86f29": (
        "As founder and CEO of a serious-injury practice, you're responsible for the "
        "whole operating picture, from intake to medical follow-up and client "
        "communication. That makes your perspective on where AI can help first "
        "especially useful."
    ),
    "26b87673-0ad8-4050-bd73-e35bea112fc7": (
        "As a founder working across personal injury and lemon-law matters, you've "
        "had to support different evidence and client-update cycles while keeping "
        "intake and follow-up consistent. That makes your perspective especially useful."
    ),
}

QUESTION_OVERRIDES = {
    "0bd3a904-a6c0-439e-b061-b4e6adc0918f": (
        "Which handoff would you most want AI to simplify: intake, client updates, or records?"
    ),
}

SUBJECT_OVERRIDES = {
    # The stored Litify evidence for SHK is not strong enough to name the vendor.
    "0bd3a904-a6c0-439e-b061-b4e6adc0918f": "AI priorities at SHK Law",
}


def fetch_rows() -> list[dict]:
    sql = text(
        """
        SELECT a.id AS action_id, a.status, a.scheduled_for,
               a.input_json->>'lead_gen_action_type' AS action_kind,
               a.input_json->>'in_reply_to' AS in_reply_to,
               a.input_json->>'references' AS references,
               a.input_json->>'transport' AS transport,
               a.input_json->>'subject' AS subject,
               a.input_json->>'body' AS body,
               i.id AS item_id, i.batch_id, i.pif_id, i.firm_name,
               i.contact_name, i.contact_email
        FROM agent_actions a
        JOIN lead_gen_batch_items i ON i.id = a.entity_id
        WHERE a.action_type = 'send_approved_lead_gen_draft'
          AND a.status = 'approved'
          AND a.scheduled_for >= CAST(:day_start AS timestamptz)
          AND a.scheduled_for < CAST(:day_end AS timestamptz)
        ORDER BY a.scheduled_for
        """
    )
    with _engine().connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sql, {"day_start": DAY_START, "day_end": DAY_END}
            ).mappings()
        ]


def qualifying_precise_counts(pif_ids: list[str]) -> dict[str, int]:
    sql = text(
        """
        SELECT canonical_pif_id, count(*) AS event_count
        FROM pif_autorespond_events
        WHERE canonical_pif_id = ANY(:pif_ids)
          AND response_sent IS TRUE
          AND test_mode IS FALSE
        GROUP BY canonical_pif_id
        """
    )
    with _engine().connect() as conn:
        return {
            str(row.canonical_pif_id): int(row.event_count)
            for row in conn.execute(sql, {"pif_ids": pif_ids})
        }


def split_body(body: str) -> tuple[str, str, str, str]:
    paragraphs = [part.strip() for part in (body or "").split("\n\n") if part.strip()]
    if len(paragraphs) < 5 or not paragraphs[0].startswith("Hi "):
        raise RuntimeError("unexpected_body_structure")
    greeting = paragraphs[0]
    hook = paragraphs[1]
    question_candidates = [
        part
        for part in paragraphs[2:]
        if "?" in part and not part.startswith("Best,")
    ]
    if len(question_candidates) != 1:
        raise RuntimeError(f"expected_one_question_paragraph:{len(question_candidates)}")
    signature = next((part for part in paragraphs if part.startswith("Best,")), "")
    if not signature:
        raise RuntimeError("missing_signature")
    return greeting, hook, question_candidates[0], signature


def compose(row: dict, precise_verified: bool) -> tuple[str, str]:
    greeting, hook, question, signature = split_body(row["body"])
    hook = HOOK_OVERRIDES.get(row["pif_id"], hook)
    question = QUESTION_OVERRIDES.get(row["pif_id"], question)

    if precise_verified:
        credibility = (
            "I'm Pranav, founder of Possible Minds; after working at McKinsey and "
            "Expedia, I began helping PI firms adopt AI in practical ways, and I came "
            "across your firm through our work with Precise Imaging, where we built a "
            "status-response system that handles roughly 600 emails a day."
        )
    else:
        credibility = (
            "I'm Pranav, founder of Possible Minds; after working at McKinsey and "
            "Expedia, I began helping PI firms adopt AI in practical ways."
        )

    if row["pif_id"] not in HOOK_OVERRIDES:
        raise RuntimeError(f"missing_person_first_hook:{row['pif_id']}")
    if question.startswith(APPRECIATION_PREFIX):
        question = question[len(APPRECIATION_PREFIX):]
    question = question[0].lower() + question[1:]
    closing = APPRECIATION_PREFIX + question

    body = "\n\n".join([greeting, hook, credibility, EMOTION, closing, signature])
    subject = SUBJECT_OVERRIDES.get(row["pif_id"], row["subject"])
    if row["action_kind"] == "first_touch" and precise_verified:
        subject = PRECISE_SUBJECT
    return subject, body


def validate_draft(row: dict, subject: str, body: str, precise_verified: bool) -> None:
    if row["action_kind"] == "follow_up" and subject != row["subject"]:
        raise RuntimeError("follow_up_subject_changed")
    if row["action_kind"] == "follow_up" and not row["in_reply_to"]:
        raise RuntimeError("follow_up_missing_in_reply_to")
    if row["action_kind"] == "follow_up" and not row["references"]:
        raise RuntimeError("follow_up_missing_references")
    if row["action_kind"] == "first_touch" and precise_verified and subject != PRECISE_SUBJECT:
        raise RuntimeError("verified_precise_subject_wrong")
    if not precise_verified and ("Precise Imaging" in body or subject == PRECISE_SUBJECT):
        raise RuntimeError("unverified_precise_reference")
    if precise_verified and "came across your firm through our work with Precise Imaging" not in body:
        raise RuntimeError("verified_precise_source_missing")
    if "McKinsey" not in body or "Expedia" not in body:
        raise RuntimeError("background_missing")
    if EMOTION not in body:
        raise RuntimeError("human_emotion_missing")
    if APPRECIATION_PREFIX not in body:
        raise RuntimeError("appreciation_missing")
    if "perspective" not in HOOK_OVERRIDES[row["pif_id"]].lower() and "view" not in HOOK_OVERRIDES[row["pif_id"]].lower() and "judgment" not in HOOK_OVERRIDES[row["pif_id"]].lower():
        raise RuntimeError("person_relevance_missing")
    if "not a pitch" in body.lower() or "sales pitch" in body.lower():
        raise RuntimeError("pitch_disclaimer_present")
    if "—" in body or "—" in subject:
        raise RuntimeError("em_dash_present")
    if body.count("?") != 1:
        raise RuntimeError(f"question_count_wrong:{body.count('?')}")
    if "\\n" in body:
        raise RuntimeError("literal_newline_escape")
    words = re.findall(r"\b[\w'-]+\b", body)
    if len(words) < 85 or len(words) > 155:
        raise RuntimeError(f"word_count_outside_guard:{len(words)}")


def update(row: dict, subject: str, body: str) -> dict:
    cmd = [
        "./bin/possibleos",
        "lead-gen",
        "edit-draft",
        row["item_id"],
        "--subject",
        subject,
        "--body",
        body,
        "--transport",
        row["transport"] or "resend",
        "--action-type",
        row["action_kind"],
        "--at",
        row["scheduled_for"].isoformat(),
        "--actor",
        "codex-updated-skill-2026-09-10",
        "--no-editor",
        "--no-execute",
        "--json",
    ]
    if row["action_kind"] == "follow_up":
        cmd.extend(["--in-reply-to", row["in_reply_to"], "--references", row["references"]])
    result = subprocess.run(cmd, cwd="/home/pranav/possibleos", text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(
            f"edit_failed:{row['item_id']}:{result.returncode}:{result.stderr[-1000:]}:{result.stdout[-1000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non_json_cli_output:{row['item_id']}:{result.stdout[-1000:]}") from exc
    return payload


def main() -> None:
    rows = fetch_rows()
    if len(rows) != 40:
        raise RuntimeError(f"expected_40_approved_scheduled_actions_found_{len(rows)}")
    if {row["batch_id"] for row in rows} != {BATCH_ID}:
        raise RuntimeError("unexpected_batch_in_today_queue")
    if any(row["scheduled_for"] <= datetime.now(timezone.utc) for row in rows):
        raise RuntimeError("scheduled_action_is_due_or_past")

    counts = qualifying_precise_counts([row["pif_id"] for row in rows])
    observed = {pif_id for pif_id, count in counts.items() if count > 0}
    if observed != VERIFIED_PRECISE_PIF_IDS:
        raise RuntimeError(
            "precise_verification_set_changed:" + json.dumps(
                {"expected": sorted(VERIFIED_PRECISE_PIF_IDS), "observed": sorted(observed)}
            )
        )

    prepared = []
    for row in rows:
        precise_verified = row["pif_id"] in observed
        subject, body = compose(row, precise_verified)
        validate_draft(row, subject, body, precise_verified)
        prepared.append((row, precise_verified, subject, body))

    results = []
    for row, precise_verified, subject, body in prepared:
        payload = update(row, subject, body)
        action = payload.get("action") or payload.get("send_action") or {}
        results.append(
            {
                "item_id": row["item_id"],
                "action_id_before": row["action_id"],
                "action_id_after": action.get("id") or payload.get("action_id"),
                "contact": row["contact_email"],
                "firm": row["firm_name"],
                "kind": row["action_kind"],
                "precise_verified": precise_verified,
                "subject": subject,
                "scheduled_for": row["scheduled_for"].isoformat(),
                "updated_existing": payload.get("updated_existing"),
            }
        )

    print(
        json.dumps(
            {
                "batch_id": BATCH_ID,
                "updated": len(results),
                "verified_precise": sum(1 for result in results if result["precise_verified"]),
                "without_precise": sum(1 for result in results if not result["precise_verified"]),
                "follow_ups": sum(1 for result in results if result["kind"] == "follow_up"),
                "first_touches": sum(1 for result in results if result["kind"] == "first_touch"),
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        raise
