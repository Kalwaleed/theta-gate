<!--
Status: drafted, awaiting post
Post from: @khaledalwaleed
Tags required by hackathon rules: X -> @lablabai @AlpacaHQ · LinkedIn -> lablab.ai + Alpaca company pages
Suggested timing: Wed 2 Sep evening or Thu 3 Sep. This is the "setbacks" post the rules explicitly ask for.
Real incident: PR #18, merged 31 Aug.
-->

## X

Setback worth sharing.

My repo-goes-public automation passed its dry run all week. A reviewer pointed out it only tested a read. The write permission it actually needed had never been exercised.

A green check proves what it calls, not what you need.

@AlpacaHQ @lablabai

## LinkedIn

Building in public means posting the misses too, so here is today's.

Part of my hackathon agent is an automation that flips the repository from private to public on a schedule, right before submission. I wrote it, ran its dry run, watched it go green, and reported it as verified.

Someone reviewing the repo pointed out that the dry run only ever called a read operation. The permission the real flip depends on — write access to repository administration — had never been exercised by that test, not once. And I already knew that same credential was missing a different permission it was assumed to have, because it had failed on it days earlier.

So I had a green check that proved the thing I was not worried about.

The fix was small: the dry run now performs a real no-op write against the actual endpoint. It has since been re-run and genuinely passes.

The lesson is not about GitHub permissions. It is that a passing test proves what it actually calls, not what the task needs — and that being reviewed by someone who did not write the code is worth more than any amount of confidence in your own.

#AlpacaHackathon #BuildInPublic
