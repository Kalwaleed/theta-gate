<!--
Status: drafted, awaiting post
Post from: @khaledalwaleed
Tags required by hackathon rules: X → @lablabai @AlpacaHQ · LinkedIn → lablab.ai + Alpaca company pages
Suggested timing: any point before or at kickoff (28 Aug 11:00 ET) — this covers pre-build verification work, not the strategy itself
-->

## X (277 chars, under 280)

Building an options agent for the @AlpacaHQ x @lablabai hackathon. First finding before writing code: priced a real SPY credit spread on paper. Expected value across every delta and width tested was negative — exactly the bid-ask cost. No arithmetic edge. Building around that.

## LinkedIn (813 chars — shortened 2026-08-27)

Starting the Alpaca AI Trading Agents Hackathon with lablab.ai — an autonomous options-trading agent on Alpaca's paper API.

First finding, before writing any strategy code: priced a real SPY credit spread live. Expected value was negative across every delta and width I tested — matching the bid-ask cost almost exactly. A fairly priced options chain doesn't hand you an edge by arithmetic. The only honest one left is the variance risk premium, and six sessions won't prove it either way.

So the design follows from that: an LLM proposes trades, but every order runs through a separate, deterministic risk guard that can't be talked out of its limits. No claim to predict the market — just a documented premium, harvested under a hard cap, reported honestly.

More as it trades. #AlpacaHackathon #BuildInPublic
