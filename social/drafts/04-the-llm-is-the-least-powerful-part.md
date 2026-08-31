<!--
Status: drafted, awaiting post
Post from: @khaledalwaleed
Tags required by hackathon rules: X -> @lablabai @AlpacaHQ · LinkedIn -> lablab.ai + Alpaca company pages
Suggested timing: Wed 2 Sep
Gate count read from risk.py (_STATE_ONLY_GATES 18 + _SIZED_GATES 3). Model constraints from brain.py's docstring.
-->

## X

The LLM in my trading agent picks two things: which ticker, and which direction.

It cannot pick a strike, a size, a price, or a threshold. No tools, no broker credentials. 21 deterministic gates own the rest.

If the model fails: no trade, never a crash.

@AlpacaHQ @lablabai

## LinkedIn

An unpopular design choice in my hackathon entry: the language model is deliberately the least powerful component in the system.

Theta Gate makes exactly one model call per tick. That call may choose an underlying, choose a direction, and write a short thesis. It may not choose a strike, an expiry, a quantity, a price, or a risk threshold. Separate deterministic Python owns every one of those, and reads nothing back from the model except five validated fields.

The model also runs with no tools at all — no filesystem, no web search, no news, no broker credential, not even the project's own MCP config. It sees the same market numbers the risk gates see, and nothing else.

Then 21 gates get the last word on every order: variance risk premium, volatility regime, delta band, credit quality, concurrency limits, loss caps, buying-power floor, drawdown halt. The first one that fails stops the trade and says why.

Every model failure collapses to one outcome: malformed JSON, a timeout, an empty response, or a prompt-injection attempt all produce no proposal — and never a crash. The exit and reconciliation paths keep running regardless, because the thing that must never break is the code that closes positions, not the code that opens them.

Autonomy is not the same as giving the model the keys.

#AlpacaHackathon #BuildInPublic
