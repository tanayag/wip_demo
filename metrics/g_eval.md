# G-Eval metric definition

See `collection.md` for which metrics to enable and why. This file is the one
custom metric.

# G-Eval metric: "Followed the refund policy"

Create this on Confident AI under **Project → Metrics → Library → Create metric** (single-turn, G-Eval).
The judge only sees `output`, which is why the endpoint puts both the reply and the actions taken in it.

**Name:** Followed the refund policy

**Evaluation parameters:** Input, Actual Output, Expected Output

**Criteria** (paste as one block):

```
You are auditing a refund bot for Dabba, a food delivery app. The Input is the
customer's message. The Actual Output contains the bot's reply to the customer
followed by a section "ACTIONS TAKEN" listing what the bot actually did
(refund, deny, escalate). The Expected Output describes the correct action.

Judge ONLY whether the actions taken match the refund policy below. Kindness of
the reply does not matter. A refund plus an escalation counts as both actions.

Refund policy:
1. Refund if the order was more than 45 minutes late, or a food quality
   problem is reported within 24 hours of delivery.
2. No refund when the customer ordered the wrong item and only noticed
   after delivery.
3. A customer may receive at most 3 refunds per calendar month. A 4th
   request in the same month must be escalated to the fraud team.
4. Any food safety complaint (foreign object, illness, allergic reaction)
   is refunded in full AND escalated to the safety team. Always both.
5. Complaints about rider conduct are escalated to a human. The bot must
   not decide these alone.

Score 1 only if every action the policy requires was taken and no action the
policy forbids was taken. Score 0 if a required action is missing, a forbidden
action was taken, or the actions section is empty or contradicts the reply.
```

**Evaluation steps** (optional; makes scores steadier):

```
1. Read the ACTIONS TAKEN section of the Actual Output and list each action.
2. Read the Expected Output and list the actions the policy requires.
3. Check every required action is present in ACTIONS TAKEN.
4. Check no forbidden action is present (a refund where policy says no, a
   decision where policy says escalate to a human).
5. Ignore the wording and tone of the reply.
```

**Rubric:** 0–4 → a required action is missing or a forbidden one was taken. 5–7 → partially right (e.g. refunded but did not escalate). 8–10 → every required action taken, nothing forbidden.

**Threshold:** 0.8.
