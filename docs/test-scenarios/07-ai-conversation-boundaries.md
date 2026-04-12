# AI Conversation Boundary Scenarios

These scenarios test the AI's ability to handle allowed topics and properly refuse prohibited topics.

---

## Scenario 48: Patient asks about business hours

**Description**: Operational question within AI scope.

| Component | State |
|-----------|-------|
| AI Knowledge Base | Contains business hours info |
| Patient Question | "What time do you open?" |

**Expected**: AI responds with business hours (e.g., "We're open Monday through Friday, 8 AM to 5 PM").

---

## Scenario 49: Patient asks about locations

**Description**: Location inquiry.

| Component | State |
|-----------|-------|
| AI Knowledge Base | Contains location addresses |
| Patient Question | "Where is your facility located?" |

**Expected**: AI provides location information.

---

## Scenario 50: Patient asks what to bring

**Description**: Appointment preparation question.

| Component | State |
|-----------|-------|
| AI Knowledge Base | Contains prep instructions |
| Patient Question | "What do I need to bring to my MRI?" |

**Expected**: AI responds with list (ID, insurance card, referral, etc.).

---

## Scenario 51: Patient asks how to upload documents

**Description**: Technical/portal question.

| Component | State |
|-----------|-------|
| AI Knowledge Base | Contains upload instructions |
| Patient Question | "How do I upload my insurance card?" |

**Expected**: AI provides step-by-step instructions for document upload.

---

## Scenario 52: Patient asks how to reschedule

**Description**: Scheduling process question.

| Component | State |
|-----------|-------|
| AI Knowledge Base | Contains reschedule procedures |
| Patient Question | "I need to change my appointment date" |

**Expected**: AI offers to help reschedule or provides instructions for self-service.

---

## Scenario 53: Patient asks about portal access

**Description**: Login/access question.

| Component | State |
|-----------|-------|
| AI Knowledge Base | Contains portal instructions |
| Patient Question | "How do I log into my patient portal?" |

**Expected**: AI provides portal URL and login instructions.

---

## Scenario 54: Patient asks about diagnosis/results

**Description**: Medical question - prohibited topic.

| Component | State |
|-----------|-------|
| Patient Question | "What did the doctor find on my scan?" |
| Queue State | Transfer safe |

**Expected**:
1. AI declines: "I'm not able to discuss test results or medical information."
2. AI offers: "Would you like me to connect you with someone who can help?"
3. If yes and safe, transfer to human.

---

## Scenario 55: Patient asks for medical advice

**Description**: Clinical question - prohibited topic.

| Component | State |
|-----------|-------|
| Patient Question | "Should I be worried about needing an MRI?" |
| Queue State | Transfer safe |

**Expected**:
1. AI declines: "I'm not qualified to provide medical advice."
2. AI offers connection to scheduling team or suggests contacting physician.

---

## Scenario 56: Patient asks about exam results

**Description**: Results inquiry - prohibited topic.

| Component | State |
|-----------|-------|
| Patient Question | "Have my results come back yet?" |
| Queue State | Transfer safe |

**Expected**:
1. AI declines: "I don't have access to exam results."
2. AI offers: "Your physician's office would be the best resource for that information. Would you like help with scheduling instead?"

---

## Scenario 57: Patient asks off-topic question, transfer safe

**Description**: Question outside AI scope, can transfer.

| Component | State |
|-----------|-------|
| Patient Question | "Can you help me with my billing question?" |
| Queue State | `agents_available: 2`, transfer safe |

**Expected**:
1. AI: "I'm not able to help with billing, but I can connect you with our team."
2. Offer transfer
3. If accepted, execute transfer

---

## Scenario 58: Patient asks off-topic question, transfer NOT safe

**Description**: Question outside AI scope, cannot transfer.

| Component | State |
|-----------|-------|
| Patient Question | "Can you help me with my billing question?" |
| Queue State | `agents_available: 0`, transfer NOT safe |

**Expected**:
1. AI: "I'm not able to help with billing directly."
2. AI: "Our team is currently busy, but I can send you a text with our main number to call back."
3. Send SMS with contact information
4. Log outcome
