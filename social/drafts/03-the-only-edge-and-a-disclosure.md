<!--
Status: drafted, awaiting post
Post from: @khaledalwaleed
Tags required by hackathon rules: X -> @lablabai @AlpacaHQ · LinkedIn -> lablab.ai + Alpaca company pages
Suggested timing: Tue 1 Sep
Thresholds read from governance.json. The disclosure is the one governance.json itself requires in the write-up.
-->

## X

The only edge my trading agent claims: implied vol must beat 10-day realised by a full point before it sells anything.

Disclosure — I re-based that window on Saturday while looking at Friday's marks. A threshold chosen with the data in view. Saying so.

@AlpacaHQ @lablabai

## LinkedIn

A fairly priced options chain has no arithmetic edge. I verified that on Alpaca's paper API before writing any strategy code: expected value across every delta and width I tested came out negative, by almost exactly the bid-ask cost.

So Theta Gate claims exactly one edge, and names it: the variance risk premium. It sells a put credit spread only when implied volatility is measurably richer than realised volatility — currently a 10-day realised window, and implied has to clear it by a full volatility point. If that condition is absent, the agent does not trade. Most ticks, it is absent.

Now the disclosure, because building in public should include the uncomfortable parts.

That 10-day window was originally 20 days, and the margin was 2.0 points, not 1.0. I changed both on Saturday — after seeing that the 20-day window was still carrying a rally from early August and was vetoing every candidate going into Monday. The reasoning is recorded in the config file itself, dated, with the numbers that prompted it.

But it remains a threshold I re-based while looking at the data it would be applied to. That is a real methodological weakness, it is in my write-up for the judges, and it is here too.

#AlpacaHackathon #BuildInPublic
