---
name: Claude-in-Chrome network capture — arm BEFORE the user clicks
description: Critical sequencing rule for the Chrome MCP's read_network_requests tool. Capture only starts when the tool is first invoked on a tab; nothing before that call is recorded. Arm before the action, not after.
type: reference
---

## The rule

`mcp__Claude_in_Chrome__read_network_requests` is **not a passive recorder**. The browser only buffers requests for a tab once you've called the tool against that tabId at least once. Anything that happened before the first invocation — including page loads, auth calls, and any UI actions the user took — is lost.

Observed behavior on 2026-04-22 in Strategy Studio capture session: user performed extensive UI work (model creation, data-source linking, relationship wiring, clicks across screens). First `read_network_requests` call after that returned the literal response:
> "No requests matching '/api/' found for this tab. Note: Network tracking starts when this tool is first called."

Zero requests captured. Full replay required.

## The pattern that works

```
1. tabs_context_mcp                    # establish tab
2. navigate (if needed)                # get user into the right UI state
3. read_network_requests(clear=true)   # ARM: starts capture, empties buffer
4. Tell user "go"
5. User performs ONE logical step      # e.g. "click Create Attribute"
6. read_network_requests               # pull the deltas
7. Repeat 3–6 per step                 # OR loop without clearing if delta is OK
```

**Rule:** any time the user is about to interact with the UI, the most recent call in the conversation should be `read_network_requests` on that tab. Treat it like pressing record on a tape deck.

## Why the gotcha is asymmetric

- DOM tools (`read_page`, `computer screenshot`, `find`) work immediately against current state — no arming needed.
- Console tool (`read_console_messages`) captures are retroactive once you ask, within a rolling buffer.
- **Network capture is NOT retroactive.** It's opt-in per tab, starts empty, and only fills after you invoke the tool.

## Practical implication for Strategy automation

When the user offers to demonstrate something in Workstation / Library / Admin & Modeling so I can learn payload shapes:
1. Don't wait for them to say "I'm done" — arm the capture before they start.
2. Keep each recorded flow tight (one model create, one attribute add, one filter, …). Long mixed sessions generate hundreds of requests and the signal is hard to find.
3. If the user has already done work before I armed: acknowledge the loss, apologize (brief), and ask them to pick the smallest slice worth redoing. Don't try to guess from screenshots what the payload was.

## Related tools that DO record retroactively
- `read_console_messages` — rolling buffer of recent console output
- `read_page` / `get_page_text` — always current DOM
- Browser DevTools itself (if user has it open) — their own Network panel works independently and they can paste specific requests if the re-record is expensive
