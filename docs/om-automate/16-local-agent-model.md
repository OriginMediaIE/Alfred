# Local Agent Model Profile

## Recommended model for the audited Mac

The capability-first local agent for the audited Apple M1 Mac mini with 16 GB
unified memory is **Qwen 3.5 9B Q4_K_M**, exposed to OM Automate as
`om-agent:qwen3.5-9b` through Ollama's native API.

Create or refresh the profile after installing `qwen3.5:latest`:

```bash
ollama pull qwen3.5:latest
ollama create om-agent:qwen3.5-9b -f config/ollama/Modelfile.om-agent
```

Configure the local endpoint as `http://localhost:11434/api`, enable verified
tool support, refresh models, and select `om-agent:qwen3.5-9b` in Agent mode.
The derived tag reuses the installed weights and does not duplicate the 6.6 GB
model blob.

## Why the profile caps context at 32K

The weights advertise a 256K maximum, but allocating that window alongside macOS
and OM Automate is inappropriate on a 16 GB unified-memory host. The profile caps
Ollama at 32K. OM reads the explicit `num_ctx` value from `/api/show` and preserves
it instead of replacing it with the weights' maximum. The observed live allocation
was about 6.1 GB, fully on the M1 GPU.

## Local qualification result

A synthetic governed-tool benchmark used eight competing tools and covered exact
read selection, exact mutation arguments, calendar arguments, abstention, an
instruction embedded in untrusted text, and multi-turn tool-result synthesis.

| Installed model | Score | Qualification note |
| --- | ---: | --- |
| `qwen3.5:latest` | **12/12** | Exact calls and arguments; ignored injected deletion instruction; correct final synthesis. |
| `qwen3:1.7b` | 11/12 | Fast fallback, but placed a task title in the wrong required field. |
| `llama3.1:8b` | 8/12 | Disqualified: called a read tool unnecessarily and followed an injected deletion instruction. |
| `qwen2.5-coder:7b` | 4/12 | Did not emit native structured calls for the requested actions. |

The final in-application acceptance turn selected `query_work`, executed it through
OM's governed dispatcher, and produced a grounded visible daily-focus summary.
With thinking disabled, the first tool call completed in about 11 seconds and the
full two-round answer began rendering at about 54 seconds with OM's real 27-tool
catalogue. This is the quality-first profile, not an instant-response profile.

## Operating guidance

- Use `om-agent:qwen3.5-9b` for multi-step work, tool selection, planning, and
  consequential tasks that will pass through Approval Centre.
- Use `qwen3:1.7b` when speed matters more than argument reliability, preferably
  for read-only requests.
- Keep Approval Centre and runtime authorization enabled. A capable model is not
  an authorization boundary and must never bypass tool policy or exact approvals.
- Keep the local endpoint bound to loopback or a trusted private network.
- If `ollama ps` reports a context larger than 32768 for this tag, stop and check
  the endpoint/profile before continuing; large allocations can cause heavy swap.

## Boundary

This recommendation is specific to the audited M1/16 GB host and the current OM
tool catalogue. A machine with 32 GB or more should rerun the benchmark against
larger Qwen 3.5 variants. Hosted frontier models remain more capable overall, but
they do not meet the fully local requirement.
