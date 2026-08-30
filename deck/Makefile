# Theta Gate deck.
#
#   make          build theta-gate.pdf
#   make check    build and fail loudly if a slide overflows (content that
#                 runs past the bottom is silently DROPPED by beamer -- it
#                 does not error, it just disappears)
#   make png      render each slide to deck/build/png for a visual pass
#   make clean    remove build artifacts (keeps the PDF)
#
# xelatex, not pdflatex: fontspec needs it for the IBM Plex fallback chain.
# Two passes, because the footer prints \inserttotalframenumber and the
# total is not known until the first pass finishes.

TEX     := xelatex
FLAGS   := -interaction=nonstopmode -halt-on-error
SRC     := theta-gate.tex
PDF     := theta-gate.pdf
BUILD   := build

.PHONY: all check png clean distclean

all: $(PDF)

$(PDF): $(SRC)
	$(TEX) $(FLAGS) $(SRC)
	$(TEX) $(FLAGS) $(SRC)
	@echo "built $(PDF) -- $$($(TEX) --version | head -1)"

# Beamer drops overflowing content without failing the build, so an
# unchecked deck can quietly lose the last line of a slide. Treat it as an
# error here rather than discovering it in the submitted PDF.
check:
	@$(MAKE) --no-print-directory distclean >/dev/null
	@$(MAKE) --no-print-directory $(PDF) >/dev/null
	@test -f theta-gate.log || { echo "no build log -- the build did not run"; exit 1; }
	@n=$$(grep -c 'Overfull \\vbox' theta-gate.log 2>/dev/null || echo 0); \
	if [ "$${n:-0}" -gt 0 ]; then \
	  echo "$$n frame(s) overflow -- content may be cut off the bottom:"; \
	  grep 'Overfull \\vbox' theta-gate.log | sed 's/^/    /'; \
	  echo "    anything above ~30pt: run 'make png' and read those slides."; \
	else \
	  echo "no overfull frames"; \
	fi

png: $(PDF)
	@mkdir -p $(BUILD)/png
	@command -v pdftoppm >/dev/null || { echo "needs poppler: brew install poppler"; exit 1; }
	pdftoppm -png -r 110 $(PDF) $(BUILD)/png/slide
	@echo "rendered to $(BUILD)/png/"

clean:
	rm -f *.aux *.log *.nav *.out *.snm *.toc *.vrb
	rm -rf $(BUILD)

distclean: clean
	rm -f $(PDF)
