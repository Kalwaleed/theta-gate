# Video — three production prompts

Companion to `VIDEO-SCRIPT.md`. That file is the source of truth for shots,
commands, and palette. These three prompts split the same 3:00 cut into the three
jobs a producer can hand off separately: the two generated bookends, the screen
capture and edit, and the narration. Nobody appears on camera.

Read `VIDEO-SCRIPT.md` once before handing any of these out. If a prompt below
disagrees with it, the script is right.

---

## Prompt 1 — Bookends (generated or shot practically, 10 seconds total)

Paste to an AI video generator, or hand to a videographer with a phone and a tripod.

> **Brief.** Produce two clips of the same empty trading desk from the same camera
> position at two times of day. They open and close a three-minute screen-capture
> video about an autonomous trading agent. The room is the argument: nobody is
> sitting in the chair, before the market or after it. Nothing in either clip may
> show a person, a hand, a reflection of a person, readable text, code, numbers,
> charts, or a logo.
>
> **Clip A — cold open, 6.0 seconds, 24 fps, 16:9, 4K.**
> Locked-off wide shot of an empty financial trading desk before dawn, photographed
> from directly behind an unoccupied ergonomic chair at seated eye level (1.15 m),
> 8–10° off-axis to camera left. Three large monitors in a shallow arc across the
> upper two-thirds of frame. The two outer monitors are fully dark. The centre
> monitor shows a black terminal with one small violet rectangular cursor blinking
> at about 1 Hz. The chair back is a soft dark mass in the lower-left third, out of
> focus. One thin shaft of cold pre-dawn window light enters from off-frame left,
> rakes across the bare desk, and catches slow dust in the air. Almost no fill;
> contrast about 8:1; shadows go to near-black. Extremely slow push-in, about 4%
> over the six seconds, linear, as if on a slider. 35mm spherical, T2.8, focus locked
> on the cursor, no rack focus. Cold desaturated grade: near-black `#0B0D0F`,
> charcoal `#5B5B5B`, and one saturated colour only, the cursor at violet `#3F2AC1`.
> Fine 35mm grain, faint halation around the cursor. Only two things move: the
> cursor blink and the dust. No curtain, reflection, flicker, or chair movement.
>
> **Clip B — outro, 4.0 seconds, 24 fps, 16:9, 4K.**
> The identical desk from the identical camera position, framing unchanged to the
> pixel, now in flat overcast midday light. All three monitors are switched off:
> dark matte grey, no glow, no cursor. Chair empty and unmoved. Desk bare. No light
> shaft, no haze, no dust. Even soft light, contrast about 2:1. Camera completely
> static, no movement at all. 35mm spherical, T4. Neutral desaturated grade, cool
> grey and charcoal, fine 35mm grain.
>
> **Negative list for both clips:** people, person, human, hands, fingers, face,
> silhouette, reflection of a person, readable text, legible code, visible numbers,
> charts, graphs, candlesticks, logos, brand marks, warm light, amber, orange, gold,
> tungsten, sunset, lens flare, bokeh balls, rack focus, handheld, camera shake,
> orbit, dolly zoom, crane, timelapse, fast motion, neon, cyberpunk, cluttered desk,
> coffee cup, plant, RGB keyboard.
>
> **Acceptance.** Generate A first and lock it; B must match A's framing, so A is
> the reference. Run four to six variations of each. Reject any take with added
> motion, invented screen content, a warm cast, or any trace of a person. If the
> generated takes look synthetic, shoot it practically: a real empty desk before
> sunrise, monitors off, one black terminal open, phone on a tripod, then a 4%
> digital push-in in the edit. A photograph carries this shot.
>
> **Deliver** two ProRes 422 or high-bitrate H.264 files, 3840×2160, 24 fps, no
> audio, no burned-in titles. Titles are added in the edit (see Prompt 2).

---

## Prompt 2 — Screen capture and edit (2:50 of real footage, plus assembly)

Hand to a videographer or editor who has access to the repo on the recording
machine. This is the only part that shows the agent working, and none of it may be
staged or generated.

> **Brief.** Record a 3:00 screen-capture video of a Python trading agent from a
> macOS machine, then assemble it with two supplied bookend clips (Clip A, Clip B)
> and a supplied narration track. The subject is an agent that refuses trades; the
> footage must show real terminal output from the repository's own journal. No
> mock-ups, no re-typed output, no synthetic frames between 0:06 and 2:56.
>
> **Setup, off camera, before recording starts.**
> - Terminal window about 120×35 characters, font legible at 720p, dark theme.
> - Second window: `streamlit run app.py` already running; one browser tab on the
>   dashboard, one on the GitHub Actions runs list. Close everything else.
> - Run `git pull` and then Command A from `VIDEO-SCRIPT.md` once, off camera, and
>   note the `ticks:` number it prints. That number goes into the narration; it
>   changes every five minutes while the market is open, so record it at the time
>   of the take.
> - Never on screen: `.env`, `env.example` with values, `alpaca doctor` output,
>   GitHub secrets pages, or any terminal where a key was pasted. The Alpaca account
>   ID `7a013821-9249-4505-8025-fb298f0931a5` may appear; the submission requires it.
> - Do not resize any window mid-take. Record at 1920×1080 or higher, 24 fps to
>   match the bookends, cursor visible, no click sounds, no system audio.
>
> **Shot list.** Each command is in `VIDEO-SCRIPT.md` under "Commands, in order".
> Run each one fresh so the screen is clean; clear the terminal between commands.
>
> | # | Timecode | On screen | Notes |
> |---|---|---|---|
> | 0 | 0:00–0:06 | Clip A | Title over the last 4 s: `THETA GATE` in IBM Plex Mono, letter-spaced, `#F5F5F5`; beneath it in IBM Plex Sans `#5B5B5B`: *an agent that cannot place a trade it should not.* Lower-left, fade in 0.5 s. |
> | 1 | 0:06–0:15 | Dashboard, book flat | **Hard cut** from Clip A, no dissolve. Hold static. |
> | 2 | 0:15–0:40 | `submission/WRITEUP.md` open in an editor, scrolled to the edge paragraph | Slow scroll only if the paragraph does not fit. |
> | 3 | 0:40–1:05 | `brain.py` open, the `ClaudeAgentOptions` block centred | Static. Do not highlight or annotate. |
> | 4 | 1:05–1:35 | Terminal, run Command A | Let it print fully. Hold on the output. |
> | 5 | 1:35–1:55 | Terminal, run Command B | The filled order, both legs. Hold. |
> | 6 | 1:55–2:20 | Terminal, run Command C | Allow/deny lists, then the reconciliation record. |
> | 7 | 2:20–2:45 | Terminal, run Command D | Takes several seconds. **Do not cut the pause.** Hold until `"git": {"skipped": "rehearsal"}` prints. If it fails, use the pytest fallback in the script. |
> | 8 | 2:45–2:56 | Dashboard, book flat | Static. |
> | 9 | 2:56–3:00 | Clip B | Title held 3 s, IBM Plex Mono `#F5F5F5`, same left margin: line 1 `github.com/Kalwaleed/theta-gate`, line 2 `7a013821-9249-4505-8025-fb298f0931a5`. |
>
> **Edit rules.**
> - Cuts only. No dissolves, wipes, zooms, or Ken Burns on screen footage.
> - No music. Narration and room tone only. If a bed is insisted on, keep it under
>   -30 dBFS and drop it entirely under shots 4–7.
> - No lower-thirds, callouts, arrows, or highlight boxes on terminal output. The
>   output is the evidence; decoration reads as staging.
> - Grade the screen capture neutral. Match the bookends to the deck palette
>   (`deck/theta-gate.pdf`): near-black `#0B0D0F`, charcoal `#5B5B5B`, violet
>   `#3F2AC1` as the single accent. Nothing warm anywhere.
> - Narration timing takes precedence over the timecodes above by up to ±3 s per
>   shot. Total runtime 3:00, not more than 3:10.
>
> **Deliver** one H.264 MP4, 1920×1080, 24 fps, AAC stereo at -16 LUFS integrated,
> plus the project file. Name it `theta-gate-submission.mp4`.

---

## Prompt 3 — Narration (voice artist or text-to-speech)

Hand to a narrator, or paste into a text-to-speech tool. If using ElevenLabs, use a
low-energy male or female narration voice, stability high, style low, no
"expressive" setting.

> **Brief.** Record the narration below for a three-minute technical video about an
> autonomous options-trading agent. The tone is a senior engineer explaining a
> system to a sceptical peer: even, unhurried, matter-of-fact. No enthusiasm, no
> selling, no upward inflection at the end of statements. Pauses are content;
> do not fill them. Target pace about 140 words per minute.
>
> **Pronunciation.** "Theta Gate" as two words. "SPY" and "QQQ" as letters:
> S-P-Y, Q-Q-Q. "DTE" as letters. "MCP" as letters. "P and L". "VRP" as letters
> or "variance risk premium" as written. "0.15" as "point one five". Dollar
> amounts as words: "plus ninety-five dollars".
>
> **Fill before recording.** Replace `[TICKS]` with the number printed by Command A
> in `VIDEO-SCRIPT.md` on the recording machine at the time of the take. Do not
> estimate it. Say it as a plain number.
>
> **Script.** Timecodes are targets, not hard marks. Leave 0.5 s of silence between
> segments.
>
> **[0:06] Segment 1**
> This agent ran [TICKS] times over six sessions and placed two trades. That
> ratio is the product.
>
> **[0:15] Segment 2**
> Before I wrote any strategy code I priced real spreads on the live chain. Swept
> zero point one five to zero point four five delta, and expected value came out
> negative every time, by almost exactly the bid-ask. Delta is the risk-neutral
> probability, so a fairly priced chain hands you nothing. So the agent claims one
> edge, names it, and refuses to trade when it is absent.
>
> **[0:40] Segment 3**
> One model call per entry window. Tools empty, MCP servers empty, one turn. It
> picks a direction. It cannot pick a strike, a size, a price, or a threshold, and
> it holds no broker credential. Prompt-inject it and you get no proposal, never a
> crash. The breach is not forbidden. It is unreachable, and a test asserts that.
>
> **[1:05] Segment 4**
> The decision log. Nine proposals, two fills. Seven times the model asked and its
> own risk layer refused: already at max positions for that underlying. Four more
> died on the variance-risk-premium gate. The premium was not there, so there was
> no trade to make. The model does not get to argue.
>
> **[1:35] Segment 5**
> The order that filled. Both legs, one broker timestamp, so there is never a
> naked leg. Negative price means credit. That is Alpaca's convention, verified
> against the raw order, not against my own log.
>
> **[1:55] Segment 6**
> A second scheduled job reconciles the broker's own view against this journal
> over Alpaca's MCP server. Two read tools allowed, every write tool denied by
> name. It cannot place an order. The thing that audits the books is not the thing
> that writes them.
>
> **[2:20] Segment 7**
> On the final afternoon the book had to be flat. That path is mandatory and had
> never run, so the agent rehearses it against a fabricated clock. It is Thursday
> morning, it thinks it is half past two, and it walks the force-close ladder on a
> real position. Dry run, sandboxed journal, the real audit trail untouched.
>
> **[2:45] Segment 8**
> Two trades, plus ninety-five dollars, two for two. Both closed themselves on
> take-profit at nine thirty-seven, five hours before that ladder was due. So the
> ladder never fired. It is tested, it is rehearsed, it has never run live, and I
> am not going to tell you otherwise. Two trades proves nothing about edge. The
> refusals are the part that is measurable.
>
> **Deliver** one WAV, 48 kHz, 24-bit, mono, peaks under -3 dBFS, no processing
> beyond a gentle high-pass. One file per segment as well, named `seg-01.wav`
> through `seg-08.wav`, so the editor can slide them independently.
