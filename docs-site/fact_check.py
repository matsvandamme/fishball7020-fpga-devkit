#!/usr/bin/env python3
"""List the facts a docs page lost between a git ref and the working copy.

A rewrite that only cuts prose keeps every fact. This checks that mechanically:
it collects, from both versions of the page,

  - numbers with their unit or context word (12 MS/s, -89.75 dB, R109, v2.3),
  - inline code spans (`zc-stream -D -8`),
  - non-blank lines inside fenced code blocks (commands and their output),

and prints each one the old version had and the new one does not. Whitespace
and Markdown emphasis are ignored, so reflowing a paragraph or turning it into
a table is not a loss.

    # run from: the repo root
    python3 docs-site/fact_check.py HEAD docs/flashing.md
    python3 docs-site/fact_check.py 15be984 docs/*.md      # several pages
    python3 docs-site/fact_check.py HEAD docs/a.md --moved-to docs/start/b.md docs/c.md

--moved-to names pages that took over part of the page's content: a fact found
in any of them counts as kept, and is reported as moved, with where.

Exit status: 0 when nothing was lost, 1 when something was, 2 on a usage error.
Without --moved-to, a fact that moved to another page shows as lost.
"""
import re
import subprocess
import sys

NUM = re.compile(
    r"(?<![\w.])[-−+]?\d[\d,.]*\s?"
    r"(?:%|°C|ppm|ppb|dBm|dBc|dBFS|dB|[kMG]?Hz|[kMG]?S/s|MS/s|[kMG]?B/s|[kMG]B|"
    r"ns|µs|us|ms|s|min|h|V|mV|mA|A|W|mW|Ω|ohm|bit|bits|bytes|x|×)?(?![\w])"
)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^\s*(```|~~~)")


def norm(s):
    s = s.replace("−", "-").replace(" ", " ")
    s = re.sub(r"[*_]{1,3}", "", s)
    return re.sub(r"\s+", " ", s).strip()


def facts(text):
    out, in_code = set(), False
    prose = []
    for line in text.splitlines():
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            if line.strip():
                out.add(("code", norm(line)))
            continue
        prose.append(line)
    body = "\n".join(prose)
    for m in CODE_SPAN.finditer(body):
        out.add(("span", norm(m.group(1))))
    plain = CODE_SPAN.sub(" ", body)
    plain = re.sub(r"\]\([^)]*\)", "]", plain)              # link targets are not facts
    plain = re.sub(r"<[^>]+>", " ", plain)                   # nor HTML attributes
    plain = re.sub(r"!\[[^\]]*\]", " ", plain)               # nor image alt text
    for m in NUM.finditer(plain):
        tok = norm(m.group(0)).rstrip(".,")
        if re.fullmatch(r"-?\d", tok):                      # bare single digits: list numbers, counts
            continue
        out.add(("number", tok.replace(" ", "")))
    return out


def at_ref(ref, path):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    if r.returncode:
        return None
    return r.stdout


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip().split("\n\n")[2], file=sys.stderr)
        return 2
    args = argv[2:]
    moved_to = []
    if "--moved-to" in args:
        i = args.index("--moved-to")
        args, moved_to = args[:i], args[i + 1:]
    dest = {m: norm(open(m).read()).replace(" ", "") for m in moved_to}
    ref, paths, lost_any = argv[1], args, False
    for path in paths:
        old = at_ref(ref, path)
        if old is None:
            print(f"{path}: not in {ref}, skipped")
            continue
        new = open(path).read()
        new_all = norm(new).replace(" ", "")
        lost, moved = [], {}
        for kind, f in sorted(facts(old) - facts(new)):
            # still present somewhere in the page (a number moved into a table
            # cell, code reformatted into a span): not lost
            key = f.replace(" ", "")
            if key in new_all:
                continue
            where = next((m for m, text in dest.items() if key in text), None)
            if where:
                moved[where] = moved.get(where, 0) + 1
            else:
                lost.append((kind, f))
        for where, n in moved.items():
            print(f"{path}: {n} fact(s) moved to {where}")
        if lost:
            lost_any = True
            print(f"{path}: {len(lost)} fact(s) lost since {ref}")
            for kind, f in lost:
                print(f"  {kind:6} {f}")
        else:
            print(f"{path}: nothing lost since {ref}")
    return 1 if lost_any else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
