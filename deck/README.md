# Deck

The PDF slides deliverable, in LaTeX/Beamer. 16:9, 13 slides.

```bash
cd deck
make          # -> theta-gate.pdf
make check    # warns if any slide overflows (see below -- this matters)
make png      # renders each slide to build/png for a visual pass
```

Needs `xelatex`. On macOS, MacTeX or BasicTeX (`brew install --cask basictex`). `make png` additionally needs `poppler` (`brew install poppler`).

## The one gotcha

**Beamer silently drops content that runs past the bottom of a slide.** It does not error; the text just isn't in the PDF. Three separate slides lost their closing paragraph this way while the build reported success.

So `make check` greps the log for `Overfull \vbox` and lists the offending lines. A handful of small overflows are expected and harmless — they're the panel borders extending a few points into the bottom margin, not lost text. **Anything above ~30pt is worth rendering and looking at.** Do not ship an edit without running `make check`, and if in doubt `make png` and read the slide.

## Before Thursday

Every P&L number is a red `[PLACEHOLDER]` and they all live on **one slide** — "What the agent did". That is deliberate: one number in one place is the only way it stays honest across edits. Do not quote a P&L anywhere else.

On Thursday 3 Sep, once the book is flat and there's a settled number:

1. Fill the four stats — realised P&L, trades closed, win rate, max drawdown. Get them from `python store.py --summary`.
2. Replace the empty chart box with the real equity curve.
3. Update the two `[n]` placeholders on "What six sessions can and cannot show".
4. `make check`, then `make png` and read all 13 slides.

`grep PLACEHOLDER theta-gate.tex` finds everything still outstanding.

## Design

Palette and type are lifted from `../docs/diagrams/*.html` and `../app.py`, so the deck, the diagrams and the live demo read as one artifact: ink `#0B0D0F`, paper `#F5F5F5`, accent `#3F2AC1`, IBM Plex.

Dependencies are limited to what ships with **TeX Live basic** — beamer, tikz, xcolor, fontspec. No `tcolorbox`, no `pgfplots`, no `plex` package, because installing those needs `tlmgr` with admin rights and this has to build on a teammate's machine without ceremony. The panels are plain tikz nodes and the architecture diagram is hand-drawn for the same reason.

Fonts degrade rather than fail: IBM Plex if installed, else Helvetica Neue, else the default sans. A missing font must never break the build two days before a deadline.

## What the deck argues

It is not a feature tour. The spine is the one claim the project is built to support:

1. Alpaca's own paper-trading skill demands a human confirmation before every order. The hackathon demands autonomy. **Those are incompatible.**
2. A confirmation is really two things — legibility and authority. Alpaca automates away the authority when no human is present and replaces it with an assertion that fails closed.
3. Theta Gate does the same, with eighteen assertions instead of one. The breach is unreachable rather than forbidden.
4. And then it states plainly what six sessions cannot show, because a judge who does the arithmetic will notice if we don't.
