# The metric collection

Two metrics. Both single-turn. Create them under **Metrics → Library**, put them in
one collection, and attach that collection to the evaluation run.

Two is a deliberate choice for the workshop. Every extra metric is another thing to
explain on stage and another thing that can misfire in front of the room.

## 1. Tool Correctness — built in, deterministic

The spine of the demo. Compares `tools_called` from the endpoint against the golden's
`expected_tools`. No LLM involved, so it cannot be argued with and cannot flake.

| setting | value | why |
|---|---|---|
| Exact match | off | the bot sometimes calls `lookup` twice; that is untidy, not wrong |
| Consider ordering | off | looking up before deciding is the only order that happens anyway |
| Check input parameters | on | this is what makes `escalate(team=human)` fail a case that needs `team=fraud` |
| Threshold | 0.8 | score is correct tools over tools called |

What it catches: refunding the serial refunder, refunding the wrong-item order,
denying the late order, deciding the rider case instead of escalating it.

## 2. Followed the refund policy — G-Eval, LLM judge

Reads the reply and the actions and grades them against the policy text. Definition,
criteria, evaluation steps and rubric are in `g_eval.md`.

| setting | value |
|---|---|
| Evaluation parameters | Input, Actual Output, Expected Output |
| Threshold | 0.8 |

What it catches that Tool Correctness cannot: escalating to the right team for the
wrong reason, a reply that contradicts the action taken, inventing policy that does
not exist ("as per our policy we refund 50%").

Show Tool Correctness first on stage. It is deterministic, so nobody can dispute it.
Then show the judge, and say plainly that a judge can be wrong on any given run,
which is why the deterministic check leads.

## Worth adding if you have time

**Argument Correctness** (built in, LLM judge). Requires `input`, `actual_output` and
`tools_called`; it is referenceless, so it needs no golden fields. It asks whether the
arguments passed to each tool make sense for the request. Catches "right tool, wrong
arguments", such as a partial refund of Rs 100 on a Rs 450 order. Overlaps with the
G-Eval metric, so add it only if the room asks how you check tool arguments.

**Faithfulness** (built in, LLM judge). The endpoint returns the refund policy in
`retrieval_context`, so this one checks whether the reply is grounded in the policy
rather than invented. Genuinely relevant, but it can be noisy about polite filler that
is not in the policy. Try it in rehearsal before trusting it on stage.

## Deliberately not used

| metric group | why not |
|---|---|
| Conversational: Knowledge Retention, Role Adherence, Conversation Completeness/Relevancy | the demo is one message in, one decision out; there is no conversation |
| Retriever RAG: Contextual Precision, Recall, Relevancy | there is no retriever; the policy is handed over whole |
| Answer Relevancy | the reply is always on topic, so it would score well on every run and teach nothing |
| Safety: Bias, Toxicity, PII Leakage, Non-Advice, Misuse, Role Violation | the failure here is a wrong decision delivered politely, which is exactly what these miss |
| Trajectory: Task Completion, Step Efficiency, Plan Adherence, Plan Quality | these read traces, not responses; only useful once `CONFIDENT_API_KEY` tracing is on |
| Hallucination, Summarization, JSON Correctness, Ragas, image metrics | not the shape of this problem |
| DAG | a deterministic custom metric worth knowing about, but Tool Correctness already gives a deterministic check without building a decision tree live |

The last row of that table is the useful one for the room: most of a metric catalogue
is irrelevant to any given product. Picking the two that match your failure mode is
the skill, not enabling everything.
