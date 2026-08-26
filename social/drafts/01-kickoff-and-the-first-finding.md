<!--
Status: drafted, awaiting post
Post from: @khaledalwaleed
Tags required by hackathon rules: X → @lablabai @AlpacaHQ · LinkedIn → lablab.ai + Alpaca company pages
Suggested timing: any point before or at kickoff (28 Aug 11:00 ET) — this covers pre-build verification work, not the strategy itself
-->

## X (277 chars, under 280)

Building an options agent for the @AlpacaHQ x @lablabai hackathon. First finding before writing code: priced a real SPY credit spread on paper. Expected value across every delta and width tested was negative — exactly the bid-ask cost. No arithmetic edge. Building around that.

## LinkedIn

Starting the Alpaca AI Trading Agents Hackathon with lablab.ai this week — an autonomous options-trading agent on Alpaca's paper API, judged over six trading sessions.

Before writing a line of strategy code, I wanted to know what I was actually building around. So I priced a real 2-leg SPY credit spread live on a paper account: fetched the chain, checked the greeks, opened the position, closed it.

The result was clarifying. Swept every strike from 0.15 to 0.45 delta across five spread widths — expected value was negative in all of them, by an amount that matched the bid-ask cost almost exactly. That's not a bug. Delta is the market's own estimate of the odds, so a fairly priced options chain can't hand you an edge by arithmetic.

The one honest edge left is the variance risk premium: implied volatility has historically run a bit ahead of what actually happens. It's real, but it's thin, and six trading sessions won't prove or disprove it either way.

So that's the actual design constraint: an LLM proposes trade ideas, but every order runs through a separate, deterministic risk guard that never learns and can't be talked out of its limits. The agent isn't claiming to predict the market. It's harvesting a documented premium under a hard cap, and I'd rather say that plainly than dress up a small sample as a strategy that "works."

More as it trades. #AlpacaHackathon #BuildInPublic
