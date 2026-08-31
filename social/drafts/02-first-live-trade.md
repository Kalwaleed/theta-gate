<!--
Status: drafted, awaiting post
Post from: @khaledalwaleed
Tags required by hackathon rules: X -> @lablabai @AlpacaHQ · LinkedIn -> lablab.ai + Alpaca company pages
Suggested timing: Mon 31 Aug evening ET, or Tue 1 Sep morning. First eligible post — 01 predates the window.
Facts checked against data/journal.jsonl and the broker order, 31 Aug 2026.
-->

## X

Day one live. The agent ran 46 ticks and placed exactly one trade: SPY put credit spread, 754/749, $5 wide, $0.61 credit, 9 DTE. Both legs filled at the same broker timestamp.

It declined the other 45. Refusing is most of what this thing does.

@AlpacaHQ @lablabai

## LinkedIn

First live trading day for Theta Gate, my entry in the Alpaca AI Trading Agents Hackathon with lablab.ai.

The agent ran 46 scheduled ticks today. It placed one trade: a SPY put credit spread, short 754 / long 749, $5 wide, $0.61 credit, nine days to expiry. Both legs filled atomically at the same broker timestamp — no naked leg, which is the failure mode that actually hurts in multi-leg options.

The other 45 ticks it declined, and that is the part I want to highlight. Twice it produced a candidate and its own risk layer blocked the order, because one position per underlying was already open. The agent does not get to argue with that.

Close of day: a small unrealised gain, roughly $0.12 per contract against a $0.61 credit. I am not going to dress that up. On a $100,000 paper account it is statistically meaningless, and a four-day sample cannot tell you whether a strategy works.

What it can show is whether the machinery is honest: every decision journalled, every gate deterministic, every refusal logged with its reason.

More as it trades.

#AlpacaHackathon #BuildInPublic
