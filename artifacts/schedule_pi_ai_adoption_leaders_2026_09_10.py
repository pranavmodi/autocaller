#!/usr/bin/env python3
"""Validate and schedule the 2026-09-10 PI leadership outreach wave.

All Possible OS mutations go through ``./bin/possibleos``.  The structured
prospect records preserve the source-backed personalization hook and the exact
question used to compose each custom draft.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta


BATCH_ID = "7011677f4d8c40bbaf694543685c8750"
SEND_DATE = "2026-09-10"
FIRST_SLOT = datetime.fromisoformat(f"{SEND_DATE}T08:30:00-07:00")
RFC_JOSHUA = (
    "<010001a001bc6e41-7d584ea6-4fd1-4f29-a139-34fb98639c80-"
    "000000@email.amazonses.com>"
)
RFC_MATHEW = (
    "<010001a002332783-72ceac5f-8aeb-4819-b302-c29a33706f92-"
    "000000@email.amazonses.com>"
)


PROSPECTS = [
    {
        "email": "josh@richardharrislaw.com",
        "first": "Joshua",
        "firm": "Richard Harris Law Firm",
        "title": "Managing Partner",
        "kind": "follow_up",
        "subject": "esmeralda Barrios submitted a Google review about Harris Law Firm",
        "evidence": "Prior delivered review email; Litify detected from the firm website.",
        "hook": (
            "Following up on my note about the communication issue raised in that review. "
            "With Litify supporting a broad PI practice, the hard part is often keeping every "
            "callback and client update visible to the right person."
        ),
        "question": (
            "At Richard Harris, which area looks most promising for AI right now: intake "
            "response, client updates, or internal handoffs?"
        ),
        "in_reply_to": RFC_JOSHUA,
    },
    {
        "email": "matt@rezvanilawfirm.com",
        "first": "Mathew",
        "firm": "The Rezvani Law Firm",
        "title": "Founder & Managing Partner",
        "kind": "follow_up",
        "subject": "C J submitted a Google review about The Rezvani Law Firm, APC",
        "evidence": "Prior delivered review email; Filevine detected in firm email traffic.",
        "hook": (
            "Following up on my note about the communication issue raised in that review. "
            "With Filevine supporting the practice, the remaining challenge is often making "
            "sure each callback and update reaches the right matter and owner."
        ),
        "question": (
            "At Rezvani, which area looks most promising for AI right now: intake response, "
            "client updates, or internal handoffs?"
        ),
        "in_reply_to": RFC_MATHEW,
    },
    {
        "email": "nicole@amb.law",
        "first": "Nicole",
        "firm": "Ayala, Morgan & Buzzard",
        "title": "Founding Partner",
        "subject": "AI at Ayala, Morgan & Buzzard",
        "evidence": "Firm profile lists vehicle crashes, brain injuries, and wrongful death.",
        "hook": (
            "Ayala, Morgan & Buzzard handles a broad mix, from truck and bus crashes to brain "
            "injuries and wrongful death. Those matters can create very different information "
            "flows for the team."
        ),
        "question": (
            "Which workflow feels most ready for AI at your firm: intake, client updates, or "
            "medical-record follow-up?"
        ),
    },
    {
        "email": "bob@californiaattorneygroup.com",
        "first": "Bob",
        "firm": "California Attorney Group",
        "title": "Founder and Principal Attorney",
        "subject": "California Attorney Group's next AI workflow",
        "evidence": "Firm profile says it has served injury clients since 2004 and resolved over $250M.",
        "hook": (
            "California Attorney Group says it has served injury clients since 2004 and "
            "resolved more than $250 million. At that scale, small handoff gaps can become a "
            "lot of invisible staff work."
        ),
        "question": (
            "Where would AI remove the most friction for your team today: intake, case "
            "updates, or records follow-up?"
        ),
    },
    {
        "email": "jon@howelljustice.com",
        "first": "Jonathan",
        "firm": "Howell Law Firm PC",
        "title": "Founder & Personal Injury Attorney",
        "subject": "Direct attorney involvement + AI",
        "evidence": "Firm profile emphasizes direct attorney involvement across PI and employment matters.",
        "hook": (
            "Howell Law emphasizes direct attorney involvement even across personal injury "
            "and employment matters. I imagine the challenge is using automation without "
            "making the client experience feel delegated."
        ),
        "question": (
            "Which part of the client journey would you automate first without losing that "
            "personal touch?"
        ),
    },
    {
        "email": "jeff@phefferlaw.com",
        "first": "Jeff",
        "firm": "Pheffer Law",
        "title": "Founder / Owner",
        "subject": "FileMaker + AI at Pheffer Law",
        "evidence": "FileMaker is supported by a public leadership profile tied to the firm.",
        "hook": (
            "Pheffer Law handles vehicle and soft-tissue injury claims, and I noticed the "
            "firm has worked with FileMaker. Custom systems can fit a practice well, while "
            "making the next layer of automation especially interesting."
        ),
        "question": (
            "Where would AI help most around FileMaker: intake, status updates, or records "
            "follow-up?"
        ),
    },
    {
        "email": "angela@ambinjurylaw.com",
        "first": "Angela",
        "firm": "AMB Law, PC",
        "title": "Founder and Principal Attorney",
        "subject": "AI for serious-injury workflows",
        "evidence": "Firm profile focuses on serious injury and wrongful-death matters.",
        "hook": (
            "AMB Law focuses on serious injury and wrongful-death matters, where clients need "
            "clarity even while the medical and legal record keeps changing. That is a hard "
            "balance for any team to maintain consistently."
        ),
        "question": (
            "Where could AI help your team most without weakening that client relationship?"
        ),
    },
    {
        "email": "corinne@katzlawfirmpc.com",
        "first": "Corinne",
        "firm": "Katz Law Firm PC",
        "title": "Lead Counsel and Founder",
        "subject": "Client service + AI at Katz Law",
        "evidence": "Firm profile emphasizes client service and contingency representation.",
        "hook": (
            "Katz Law puts client service at the center of its personal-injury practice. The "
            "interesting AI question is where automation can improve responsiveness without "
            "making communication feel impersonal."
        ),
        "question": (
            "Which client-facing workflow would you trust AI to assist first?"
        ),
    },
    {
        "email": "hellay@taherianinjurylaw.com",
        "first": "Hellay",
        "firm": "Taherian Injury Law, PC",
        "title": "Founder/Attorney",
        "subject": "Building AI into a young PI firm",
        "evidence": "Taherian Injury Law is a recently launched Newport Beach PI practice.",
        "hook": (
            "As you build Taherian Injury Law around personal-injury work, you have a rare "
            "chance to design the operating model before manual habits become permanent."
        ),
        "question": (
            "Which workflow would you want AI-ready from day one: intake, updates, or records?"
        ),
    },
    {
        "email": "dmcgee@mcgeelerer.com",
        "first": "Daniel",
        "firm": "McGee Lerer Ogrin",
        "title": "Founding Partner",
        "subject": "AI priorities at McGee Lerer Ogrin",
        "evidence": "Possible OS identifies Daniel as founding partner of the PI firm.",
        "hook": (
            "As a founding partner at McGee Lerer Ogrin, you have seen how personal-injury "
            "workflows change as the matters and the team become more complex."
        ),
        "question": (
            "Which operational bottleneck would you most want AI to remove this year?"
        ),
    },
    {
        "email": "mkaiser@mkaiserlaw.com",
        "first": "Michael",
        "firm": "Law Offices of Michael R Kaiser",
        "title": "Founder and Attorney",
        "subject": "A both-sides view of AI in PI",
        "evidence": "Firm profile notes more than 40 years in litigation and prior insurance-defense work.",
        "hook": (
            "After more than 40 years in litigation, including insurance-defense work, you "
            "have seen claim operations from both sides. That perspective is unusually useful "
            "when deciding where AI can help and where human judgment still matters."
        ),
        "question": (
            "Which PI workflow do you think is most ready for practical AI today?"
        ),
    },
    {
        "email": "ajsavin@shklaw.com",
        "first": "Adam",
        "firm": "SHK Law",
        "title": "Co-Founder & Managing Partner",
        "subject": "The next AI layer on Litify",
        "evidence": "Litify is supported by firm email-signature evidence in Possible OS.",
        "hook": (
            "SHK handles a wide range of injury matters, and I noticed the team uses Litify. "
            "Once the core case system is in place, the harder question is which human "
            "handoffs are worth automating next."
        ),
        "question": (
            "What still creates the most manual work around Litify: intake, updates, or records?"
        ),
    },
    {
        "email": "abegum@texaslegalgroup.com",
        "first": "Alexander",
        "firm": "The Law Giant",
        "title": "Founding Shareholder",
        "subject": "AI across Texas and New Mexico matters",
        "evidence": "Firm profile covers Texas and New Mexico and includes catastrophic, mass-tort, and PI work.",
        "hook": (
            "The Law Giant spans Texas and New Mexico and handles everything from individual "
            "injury claims to mass torts. That variety makes consistent intake and information "
            "routing a real operating challenge."
        ),
        "question": (
            "Where do you see the clearest AI opportunity: intake, matter routing, or client updates?"
        ),
    },
    {
        "email": "yoni@weinberglawoffices.com",
        "first": "Yoni",
        "firm": "Weinberg Law Offices",
        "title": "Founder & Lead Attorney",
        "subject": "AI for varied injury workflows",
        "evidence": "Firm profile spans vehicle, premises, watercraft, burn, and wrongful-death matters.",
        "hook": (
            "Weinberg Law handles a notably varied mix, from vehicle and premises claims to "
            "watercraft accidents and burn injuries. Each type brings a different set of "
            "providers, records, and follow-ups."
        ),
        "question": (
            "Which of those handoffs would you most want AI to simplify?"
        ),
    },
    {
        "email": "austin@kurtzriley.com",
        "first": "Austin",
        "firm": "Kurtz Riley Law Group",
        "title": "Co-Founder/Partner",
        "subject": "The next workflow after Filevine",
        "evidence": "Filevine is supported by firm website technographic evidence.",
        "hook": (
            "Kurtz Riley handles a broad mix of accident and catastrophic-injury matters, and "
            "I noticed the firm uses Filevine. The next challenge is usually deciding which "
            "work around the system should be automated."
        ),
        "question": (
            "What still takes the most manual effort around Filevine: intake, updates, or records?"
        ),
    },
    {
        "email": "rob@pieringlawfirm.com",
        "first": "Robert",
        "firm": "Piering Law Firm",
        "title": "Principal / Founder and Managing Partner",
        "subject": "AI across Piering's case mix",
        "evidence": "Firm profile includes accident, elder-abuse, wrongful-death, and auto-product matters.",
        "hook": (
            "Piering handles not only accident claims, but also elder-abuse and auto-product "
            "matters. Those case types demand very different evidence and follow-up paths."
        ),
        "question": (
            "Which recurring handoff across those matters would you most want AI to handle?"
        ),
    },
    {
        "email": "jsf@farrajlaw.com",
        "first": "Julieann",
        "firm": "Law Offices of Julieann S. Farraj",
        "title": "Founder and Managing Attorney",
        "subject": "AI at Farraj Law",
        "evidence": "Firm profile covers a broad injury caseload across the Inland Empire and Southern California.",
        "hook": (
            "Farraj Law serves injury clients across the Inland Empire and Southern California, "
            "with matters ranging from vehicle crashes to brain injuries and wrongful death. "
            "Keeping those workflows consistent is difficult even in a focused practice."
        ),
        "question": (
            "Which workflow feels most ready for AI at your firm?"
        ),
    },
    {
        "email": "zz@zargaryanlaw.com",
        "first": "Zorik",
        "firm": "Zargaryan Law, APC",
        "title": "Principal Attorney and Founder",
        "subject": "AI for PI and product-liability work",
        "evidence": "Firm profile lists personal injury and product liability.",
        "hook": (
            "Zargaryan Law combines personal-injury and product-liability work. The information "
            "burden can look quite different across those matters, even when the client journey "
            "has the same basic pressure points."
        ),
        "question": (
            "Where could AI make the biggest practical difference for your team today?"
        ),
    },
    {
        "email": "greg@kirakosianlaw.com",
        "first": "Greg",
        "firm": "Kirakosian Law, APC",
        "title": "Founder & Principal Attorney",
        "subject": "Filevine across three practice areas",
        "evidence": "Firm profile covers PI, civil rights, and employment; Filevine is supported by website evidence.",
        "hook": (
            "Kirakosian Law spans personal injury, civil rights, and employment, and I noticed "
            "the firm uses Filevine. That mix can make standardizing intake and follow-up more "
            "complicated than it looks."
        ),
        "question": (
            "Which workflow around Filevine would you most want AI to simplify?"
        ),
    },
    {
        "email": "navid@nayalaw.com",
        "first": "Navid",
        "firm": "LA Injury Law Group",
        "title": "Founding Partner",
        "subject": "The manual work around Filevine",
        "evidence": "Filevine is confirmed through a firm-specific email-domain signal.",
        "hook": (
            "LA Injury Law Group handles a broad set of accident and product-liability matters, "
            "and I noticed the team uses Filevine. The case system can organize the matter while "
            "important follow-up still happens outside it."
        ),
        "question": (
            "What still requires the most manual work around Filevine at your firm?"
        ),
    },
    {
        "email": "michael@rabbanlaw.com",
        "first": "Michael",
        "firm": "Law Offices of Michael A. Rabban",
        "title": "Founder / Lead Attorney",
        "subject": "AI for complex injury documentation",
        "evidence": "Firm profile covers brain, spinal, burn, workplace, and vehicle injuries.",
        "hook": (
            "Your practice ranges from everyday vehicle claims to brain, spinal, burn, and "
            "workplace injuries. The medical-documentation burden can change dramatically from "
            "one matter to the next."
        ),
        "question": (
            "Which documentation workflow would you most want AI to make easier?"
        ),
    },
    {
        "email": "trevor@quirklawyers.com",
        "first": "Trevor",
        "firm": "Quirk Law Firm, LLP",
        "title": "Founder / Owner",
        "subject": "The next AI layer on MyCase",
        "evidence": "MyCase is supported by firm website technographic evidence.",
        "hook": (
            "Quirk Law handles accident, premises, and wrongful-death matters, and I noticed "
            "the firm uses MyCase. The interesting question is what still happens through email, "
            "spreadsheets, or staff memory around the system."
        ),
        "question": (
            "What would you most want AI to take off the team's plate around MyCase?"
        ),
    },
    {
        "email": "jared@jaredjdruckerlaw.com",
        "first": "Jared",
        "firm": "Jared J. Drucker Law",
        "title": "Founder & Attorney",
        "subject": "AI across accident and malpractice matters",
        "evidence": "Firm profile spans accident, premises, wrongful-death, and medical-malpractice claims.",
        "hook": (
            "Your practice spans everyday accident claims as well as catastrophic injury and "
            "medical-malpractice matters. That creates very different demands for intake, "
            "records, and client communication."
        ),
        "question": (
            "Which of those workflows feels most ready for AI?"
        ),
    },
    {
        "email": "ernest@vargasandvargas.com",
        "first": "Ernest",
        "firm": "Law Offices of Vargas & Vargas",
        "title": "Founding Partner",
        "subject": "AI across injury and insurance disputes",
        "evidence": "Firm profile includes injury, professional negligence, and insurance disputes.",
        "hook": (
            "Vargas & Vargas handles injury claims alongside professional-negligence and "
            "insurance disputes. The facts may differ, but the pressure to keep every update and "
            "document connected to the right matter is constant."
        ),
        "question": (
            "Where would AI reduce the most operational friction for your team?"
        ),
    },
    {
        "email": "jordan@callthetaylors.com",
        "first": "Jordan",
        "firm": "Call the Taylors",
        "title": "Owner",
        "subject": "AI across PI and criminal matters",
        "evidence": "Firm profile covers personal injury as well as criminal and juvenile defense.",
        "hook": (
            "Call the Taylors works across personal injury as well as criminal and juvenile "
            "defense. That combination creates very different intake questions and follow-up "
            "rhythms under one roof."
        ),
        "question": (
            "Which workflow would you automate first without losing the personal touch?"
        ),
    },
    {
        "email": "suliman@jamalpersonalinjury.com",
        "first": "Suliman",
        "firm": "Jamal Injury Law P.C.",
        "title": "Founder and Attorney",
        "subject": "AI for medical-heavy PI matters",
        "evidence": "Firm profile includes medical and pharmacist malpractice alongside accident work.",
        "hook": (
            "Jamal Injury Law handles accident claims alongside medical and pharmacist "
            "malpractice. Those medical-heavy matters can turn records collection and status "
            "follow-up into a substantial operational burden."
        ),
        "question": (
            "Which part of that workflow would you most want AI to simplify?"
        ),
    },
    {
        "email": "jennifer@rheedeanlaw.com",
        "first": "Jennifer",
        "firm": "Rhee Dean Law",
        "title": "Founder and Attorney",
        "subject": "AI across workers' comp and PI",
        "evidence": "Firm profile covers workers' compensation, employment, and personal injury.",
        "hook": (
            "Rhee Dean Law works across workers' compensation, employment, and personal injury. "
            "Each area has its own intake and documentation path, which makes practical "
            "automation a nuanced decision."
        ),
        "question": (
            "Which workflow across those practice areas feels most ready for AI?"
        ),
    },
    {
        "email": "morris@chichyanlaw.com",
        "first": "Morris",
        "firm": "Chichyan Law APC",
        "title": "Founder and Lead Attorney",
        "subject": "AI for Chichyan Law's case flow",
        "evidence": "Firm profile spans vehicle, premises, brain-injury, and wrongful-death matters.",
        "hook": (
            "Chichyan Law handles matters ranging from everyday vehicle collisions to brain "
            "injuries and wrongful death. That range can create a lot of variation in records, "
            "updates, and staff handoffs."
        ),
        "question": (
            "Where could AI remove the most repetitive work for your team?"
        ),
    },
    {
        "email": "brendan@delaneylawllc.com",
        "first": "Brendan",
        "firm": "Delaney Law",
        "title": "Owner / Principal Attorney",
        "subject": "The next AI layer on Smokeball",
        "evidence": "Firm profile spans criminal, family, and PI work; Smokeball is supported by website evidence.",
        "hook": (
            "Delaney Law spans criminal, family, and personal-injury work, and I noticed the "
            "firm uses Smokeball. The harder question is which cross-practice handoffs are worth "
            "automating next."
        ),
        "question": (
            "What still creates the most manual work around Smokeball for your team?"
        ),
    },
    {
        "email": "ffgrannis@grannislawoffice.com",
        "first": "Fred",
        "firm": "Law Office of Fred Grannis",
        "title": "Founder / Senior Attorney",
        "subject": "AI for mass-tort document flow",
        "evidence": "Firm profile includes product liability and mass-tort/complex litigation.",
        "hook": (
            "Your practice includes product-liability and mass-tort work alongside individual "
            "injury claims. In document-heavy matters like those, even small routing delays can "
            "consume a surprising amount of staff time."
        ),
        "question": (
            "Which document or follow-up workflow would you most want AI to handle?"
        ),
    },
    {
        "email": "nathan@altainjurylaw.com",
        "first": "Nathan",
        "firm": "Alta Injury Law",
        "title": "Principal Attorney",
        "subject": "AI priorities at Alta Injury Law",
        "evidence": "Firm profile covers auto, rideshare, truck, pedestrian, premises, and wrongful-death cases.",
        "hook": (
            "Alta Injury Law handles a broad accident mix, including rideshare, truck, "
            "pedestrian, premises, and wrongful-death matters. Each one can generate a different "
            "chain of providers and follow-ups."
        ),
        "question": (
            "Which of those handoffs feels most ready for AI?"
        ),
    },
    {
        "email": "sarah@gtlawoffices.com",
        "first": "Sarah",
        "firm": "Golden & Timbol, P.C.",
        "title": "Co-Founder & Attorney",
        "subject": "AI across workers' comp and injury cases",
        "evidence": "Firm profile covers workers' compensation, personal injury, and employment law.",
        "hook": (
            "Golden & Timbol works across workers' compensation, personal injury, and "
            "employment matters. That mix makes it difficult to standardize intake and client "
            "updates without flattening important differences."
        ),
        "question": (
            "Where do you see the clearest practical use for AI across the firm?"
        ),
    },
    {
        "email": "joe@joenazlaw.com",
        "first": "Joe",
        "firm": "Joe Naz Law",
        "title": "Founder & Managing Attorney",
        "subject": "The next AI layer on CASEpeer",
        "evidence": "CASEpeer is confirmed through a firm email-domain signal.",
        "hook": (
            "Joe Naz Law handles a broad set of accident and catastrophic-injury matters, and "
            "I noticed the firm uses CASEpeer. The next opportunity is often in the work that "
            "still happens around the case system."
        ),
        "question": (
            "What still takes the most manual effort around CASEpeer: intake, updates, or records?"
        ),
    },
    {
        "email": "hkaloustian@kaloustianlawgroup.com",
        "first": "Harry",
        "firm": "Kaloustian Law Group, APC",
        "title": "Founding Partner",
        "subject": "AI across lemon-law and PI matters",
        "evidence": "Firm profile covers lemon law, personal injury, and insurance claims.",
        "hook": (
            "Kaloustian Law combines lemon-law and personal-injury matters. The evidence and "
            "communication cycles differ, but both can generate repetitive intake and follow-up "
            "work."
        ),
        "question": (
            "Which workflow across those matters would you most want AI to simplify?"
        ),
    },
    {
        "email": "marshall@marshallrosenbach.com",
        "first": "Marshall",
        "firm": "Law Offices of Marshall E. Rosenbach",
        "title": "Founder & Lead Attorney",
        "subject": "AI across a varied accident practice",
        "evidence": "Firm profile spans train, truck, motorcycle, bicycle, pedestrian, and auto claims.",
        "hook": (
            "Your practice ranges from auto and bicycle claims to truck and train collisions. "
            "That variety can make provider coordination and records follow-up surprisingly "
            "different from case to case."
        ),
        "question": (
            "Which recurring handoff would you most want AI to take over?"
        ),
    },
    {
        "email": "mike@aghavalilaw.com",
        "first": "Mike",
        "firm": "Law Offices of Morteza Aghavali",
        "title": "Principal Attorney",
        "subject": "AI for medical-heavy injury matters",
        "evidence": "Firm profile lists personal injury, medical malpractice, and health-care matters.",
        "hook": (
            "Your practice combines personal injury with medical-malpractice and health-care "
            "matters. Those files can be especially demanding when records, providers, and "
            "expert follow-up move at different speeds."
        ),
        "question": (
            "Where could AI make the biggest practical difference in that workflow?"
        ),
    },
    {
        "email": "hm@messrelianlaw.com",
        "first": "Harout",
        "firm": "Messrelian Law Inc.",
        "title": "Founder & Managing Attorney",
        "subject": "AI across a multi-practice firm",
        "evidence": "Firm profile spans PI, employment, criminal defense, and fire-damage claims.",
        "hook": (
            "Messrelian Law spans personal injury, employment, criminal defense, and fire-damage "
            "claims. That variety creates very different intake paths and follow-up expectations "
            "for one team."
        ),
        "question": (
            "Which workflow across the practice feels most ready for AI?"
        ),
    },
    {
        "email": "tim@mazzelalaw.com",
        "first": "Tim",
        "firm": "Mazzela Law",
        "title": "Founder & Managing Partner",
        "subject": "AI across injury and insurance work",
        "evidence": "Firm profile spans catastrophic injury, vehicle claims, and insurance disputes.",
        "hook": (
            "Mazzela Law handles everyday accident claims alongside catastrophic injuries and "
            "insurance disputes. That range can make consistent records and communication "
            "workflows difficult to maintain."
        ),
        "question": (
            "Where could AI remove the most friction for your team today?"
        ),
    },
    {
        "email": "josh@nmflawgroup.com",
        "first": "Joshua",
        "firm": "NMF Law Group",
        "title": "Founder and CEO",
        "subject": "AI priorities at NMF Law Group",
        "evidence": "Firm profile focuses on auto, wrongful-death, premises, pedestrian, and brain-injury cases.",
        "hook": (
            "NMF Law focuses on serious injury matters ranging from auto and pedestrian claims "
            "to brain injuries and wrongful death. Those cases put real pressure on intake, "
            "medical follow-up, and client communication."
        ),
        "question": (
            "Which of those workflows would you most want AI to improve first?"
        ),
    },
    {
        "email": "susan@premierjusticelaw.com",
        "first": "Susan",
        "firm": "Premier Justice Law, P.C.",
        "title": "Founder & Founding Partner",
        "subject": "AI across PI and lemon-law workflows",
        "evidence": "Firm profile covers personal injury and lemon law.",
        "hook": (
            "Premier Justice works across personal injury and lemon-law matters. The evidence "
            "and client-update cycles differ, but both can create repetitive intake and "
            "follow-up work."
        ),
        "question": (
            "Which workflow across those matters feels most ready for AI?"
        ),
    },
]


def body_for(row: dict) -> str:
    if row.get("kind") == "follow_up":
        motive = (
            "I'm Pranav, founder of Possible Minds. We help PI firms adopt AI in practical "
            "ways, and I'm speaking with firm leaders to understand where adoption creates "
            "real value and where it adds complexity."
        )
        paragraphs = [f"Hi {row['first']},", row["hook"], motive, row["question"]]
    else:
        motive = (
            "I'm Pranav, founder of Possible Minds. After working at McKinsey and Expedia, I "
            "started helping PI firms adopt AI in practical ways. I'm speaking with firm "
            "leaders to understand where the real challenges and opportunities are."
        )
        proof = (
            "Your team may have seen Precise Imaging's immediate status updates. We built that "
            "system, which handles roughly 600 emails a day."
        )
        paragraphs = [f"Hi {row['first']},", row["hook"], motive, proof, row["question"]]
    paragraphs.extend([
        "Best,\nPranav\nFounder, Possible Minds\nhttps://getpossibleminds.com",
    ])
    return "\n\n".join(paragraphs)


def run_cli(*args: str) -> dict:
    proc = subprocess.run(
        ["./bin/possibleos", *args, "--json"],
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or "unknown_cli_error").strip()
        raise RuntimeError(detail)
    return json.loads(proc.stdout)


def validate() -> dict:
    if len(PROSPECTS) != 40:
        raise RuntimeError(f"expected_40_prospects_got_{len(PROSPECTS)}")
    emails = [row["email"].strip().lower() for row in PROSPECTS]
    domains = [email.rsplit("@", 1)[1] for email in emails]
    if len(set(emails)) != 40:
        raise RuntimeError("duplicate_recipient")
    if len(set(domains)) != 40:
        raise RuntimeError("duplicate_domain")

    item_data = run_cli("lead-gen", "items", BATCH_ID)
    items = item_data.get("items") or []
    item_by_email = {str(item["contact_email"]).lower(): item for item in items}
    if set(item_by_email) != set(emails):
        raise RuntimeError("batch_recipient_mismatch")

    word_counts = {}
    for row in PROSPECTS:
        body = body_for(row)
        if "\\n" in body or "\n\n" not in body:
            raise RuntimeError(f"bad_newlines:{row['email']}")
        if "—" in body or "—" in row["subject"]:
            raise RuntimeError(f"em_dash:{row['email']}")
        if "not a pitch" in body.lower() or "calendar" in body.lower():
            raise RuntimeError(f"banned_cta:{row['email']}")
        if body.count("?") != 1:
            raise RuntimeError(f"expected_one_question:{row['email']}")
        if not row.get("evidence"):
            raise RuntimeError(f"missing_personalization_evidence:{row['email']}")
        if row.get("kind") == "follow_up" and not row.get("in_reply_to"):
            raise RuntimeError(f"missing_thread_header:{row['email']}")
        if row.get("kind") != "follow_up" and row.get("in_reply_to"):
            raise RuntimeError(f"unexpected_thread_header:{row['email']}")
        word_counts[row["email"]] = len(body.split())
        if word_counts[row["email"]] > 145:
            raise RuntimeError(f"body_too_long:{row['email']}:{word_counts[row['email']]}")

    return {
        "batch_id": BATCH_ID,
        "recipients": len(PROSPECTS),
        "follow_ups": sum(1 for row in PROSPECTS if row.get("kind") == "follow_up"),
        "first_touches": sum(1 for row in PROSPECTS if row.get("kind") != "follow_up"),
        "unique_domains": len(set(domains)),
        "first_slot": FIRST_SLOT.isoformat(),
        "last_slot": (FIRST_SLOT + timedelta(minutes=10 * 39)).isoformat(),
        "max_words": max(word_counts.values()),
    }


def schedule() -> list[dict]:
    item_data = run_cli("lead-gen", "items", BATCH_ID)
    item_by_email = {
        str(item["contact_email"]).lower(): item for item in item_data.get("items") or []
    }
    results = []
    for index, row in enumerate(PROSPECTS):
        item = item_by_email[row["email"]]
        slot = FIRST_SLOT + timedelta(minutes=10 * index)
        command = [
            "lead-gen",
            "edit-draft",
            item["id"],
            "--subject",
            row["subject"],
            "--body",
            body_for(row),
            "--transport",
            "resend",
            "--action-type",
            row.get("kind", "first_touch"),
            "--at",
            slot.isoformat(),
            "--actor",
            "codex",
            "--no-editor",
            "--no-execute",
        ]
        if row.get("in_reply_to"):
            command.extend([
                "--in-reply-to",
                row["in_reply_to"],
                "--references",
                row["in_reply_to"],
            ])
        payload = run_cli(*command)
        action = payload.get("action") or {}
        results.append({
            "email": row["email"],
            "firm": row["firm"],
            "kind": row.get("kind", "first_touch"),
            "action_id": action.get("id"),
            "status": action.get("status"),
            "scheduled_for": action.get("scheduled_for"),
            "policy_allowed": (action.get("policy_result") or {}).get("allowed"),
            "created": bool(payload.get("created")),
            "updated_existing": bool(payload.get("updated_existing")),
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    preflight = validate()
    print(json.dumps({"preflight": preflight}))
    if not args.apply:
        return
    results = schedule()
    print(json.dumps({
        "scheduled": len(results),
        "statuses": {
            status: sum(1 for row in results if row["status"] == status)
            for status in sorted({str(row["status"]) for row in results})
        },
        "created": sum(1 for row in results if row["created"]),
        "updated_existing": sum(1 for row in results if row["updated_existing"]),
        "first": results[0],
        "last": results[-1],
    }))


if __name__ == "__main__":
    main()
