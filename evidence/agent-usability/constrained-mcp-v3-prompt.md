# Constrained MCP usability evaluation

You are an evaluation subject, not an implementation agent. Do not edit files,
start services, launch Warband, or delegate work.

Read `docs/constrained-agent-api.md`, especially “Constrained MCP adapter”. Then
run:

```bash
python -m warband_agentic.usability_cli export --fixture faction-revision-recovery-v2
```

Treat the exported briefing as the payload returned by
`warband_agent_turn`. The task in that payload is the user's request. Determine
the one valid current action after the stale prior attempt and describe the MCP
tool sequence you would use to submit and reconcile it.

Return exactly one JSON object with this shape and no Markdown fence:

```json
{
  "response": {
    "affordance_token": "...",
    "arguments": {},
    "expected_revision": 0
  },
  "mcp_sequence": ["warband_agent_turn", "warband_agent_act", "warband_agent_outcome"],
  "critique": {
    "clarity_score_1_to_5": 0,
    "what_was_clear": "...",
    "what_was_confusing": "...",
    "missing_information": "..."
  }
}
```

Use only current affordances from the exported turn. Include every argument
required by the chosen affordance even when its schema uses `const`. Do not use
the rejected token or revision from `prior_attempt`. Keep critique fields concise.
