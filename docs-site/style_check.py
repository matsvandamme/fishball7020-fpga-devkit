#!/usr/bin/env python3
"""Check the documentation's house rules that a build cannot see.

    # run from: the repo root
    python3 docs-site/style_check.py docs/            # every page under docs/
    python3 docs-site/style_check.py docs/start/      # one section
    python3 docs-site/style_check.py --counts docs/   # totals per rule only

Three rules:

  table-in-callout   No table inside a callout (a `!!!` or `???` block). A
                     table belongs below the callout; short facts are a list.
  python-venv        Python on the PC runs in a venv: `.venv/bin/pip install`
                     and `.venv/bin/python script.py`, never a bare `pip
                     install` or `python script.py`. Blocks that run on the
                     board are exempt (its Debian root uses apt packages), and
                     so is `python3 -m venv`. A script that needs nothing but
                     Python itself may be run bare when its line says so with
                     a trailing `# stdlib only`.
  run-from           Every Python or fish code block opens with a line saying
                     where it runs: `# run from: ...` or `# run on ...`.
                     (docs/check_links.py checks the same for shell blocks.)

Exit status: 0 when clean, 1 when a rule is broken, 2 on a usage error. CI
runs it on docs/ (.github/workflows/docs.yml).
"""
import pathlib
import re
import sys

CALLOUT = re.compile(r"^(\s*)(!!!|\?\?\?\+?)\s+\w+")
FENCE = re.compile(r"^(\s*)(```+|~~~+)\s*([\w+-]*)")
BARE_PIP = re.compile(r"(?<![\w./\\-])pip3?\s+install\b")
BARE_PY = re.compile(r"(?:^\s*|[;&|]\s*|sudo\s+)(python3?)\s+(?!-m\s+venv\b)(?:-\S+\s+)*\S+\.py\b")
VENV = re.compile(r"\.venv[/\\](?:bin|Scripts)[/\\]")
ON_BOARD = re.compile(r"\bboard\b", re.I)
RUN_FROM = re.compile(r"^\s*(#|%|//)\s*run (from|on)\b", re.I)
SKIP = {"course"}


def pages(arg):
    p = pathlib.Path(arg)
    if p.is_file():
        return [p]
    return sorted(f for f in p.rglob("*.md") if not SKIP & set(f.parts))


def check(path):
    problems = []
    lines = path.read_text().splitlines()

    def add(n, rule, msg):
        problems.append((rule, f"{path}:{n}: {rule}: {msg}"))

    callout_indent = None          # indent of the callout we are inside, if any
    fence = None                   # (marker, lang, first_content_line_seen, on_board)
    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # --- inside a fenced code block
        if fence:
            marker, lang, seen_first, on_board = fence
            if stripped.startswith(marker) and stripped.strip("`~") == "":
                fence = None
                continue
            if not seen_first and stripped:
                if lang in ("python", "py", "fish") and not RUN_FROM.match(line):
                    add(n, "run-from", f"{lang} block does not open with '# run from: ...'")
                on_board = bool(RUN_FROM.match(line) and ON_BOARD.search(line)
                                and not re.search(r"\b(PC|host|repo)\b", line, re.I))
                fence = (marker, lang, True, on_board)
            if not on_board and "stdlib only" not in line and not VENV.search(line):
                if BARE_PIP.search(line):
                    add(n, "python-venv", f"bare pip install: {stripped[:70]}")
                elif lang in ("bash", "sh", "shell", "console", "fish", "text", "") and BARE_PY.search(line.split("#")[0]):
                    add(n, "python-venv", f"bare python: {stripped[:70]}")
            continue

        m = FENCE.match(line)
        if m:
            fence = (m.group(2)[:3], m.group(3).lower(), False, False)
            continue

        # --- callouts: a block opened by !!! / ???, holding everything indented deeper
        if callout_indent is not None and stripped and indent <= callout_indent:
            callout_indent = None
        c = CALLOUT.match(line)
        if c:
            callout_indent = len(c.group(1))
            continue
        if callout_indent is not None and stripped.startswith("|"):
            add(n, "table-in-callout", "a table inside a callout")
            callout_indent = None  # one report per callout

        # --- prose: inline `pip install ...` outside a venv
        for span in re.findall(r"`([^`\n]+)`", line):
            if BARE_PIP.search(span) and not VENV.search(span):
                add(n, "python-venv", f"bare pip install in text: `{span[:60]}`")
    return problems


def main(argv):
    counts_only = "--counts" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    problems = [p for a in args for f in pages(a) for p in check(f)]
    rules = ("table-in-callout", "python-venv", "run-from")
    if not counts_only:
        for _, msg in problems:
            print(msg)
    for r in rules:
        print(f"{r}: {sum(1 for rule, _ in problems if rule == r)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
