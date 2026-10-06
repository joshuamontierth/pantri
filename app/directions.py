"""Recipe directions are stored as plain text and split into steps for display.

A new step starts after a blank line, or at a line that begins with a step marker
("1.", "2)", "Step 3:", "-", "•"). Lines that each end a sentence are steps too, but
a paragraph that just wraps onto the next line stays one step. A short line ending
in a colon ("For the sauce:") is a section heading.
"""

import re

MAX_LENGTH = 20_000

# "1." / "2)" / "3:" only when followed by a space, so "1.5 cups" isn't a step marker.
_MARKER = re.compile(r"^(?:step\s*\d{1,2}\b\s*[.):-]?|\d{1,2}[.):](?=\s)|[-*•·](?=\s))\s*", re.I)
_ENDS_SENTENCE = re.compile(r"[.!?:)]['\"”’]?$")


def normalize(text):
    """Tidy typed or pasted directions for storage."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def join_steps(steps):
    """Directions text from a list of step strings, one step per paragraph."""
    cleaned = [re.sub(r"\s+", " ", s).strip() for s in steps]
    return "\n\n".join(s for s in cleaned if s)[:MAX_LENGTH]


def _chunks(text):
    """Lists of lines, one list per step or heading."""
    for para in re.split(r"\n\s*\n", normalize(text)):
        lines = [line.strip() for line in para.split("\n") if line.strip()]
        groups, cur = [], []
        for line in lines:
            if cur and _MARKER.match(line):
                groups.append(cur)
                cur = []
            cur.append(line)
        if cur:
            groups.append(cur)
        for group in groups:
            if len(group) > 1 and all(_ENDS_SENTENCE.search(line) for line in group):
                yield from ([line] for line in group)
            else:
                yield group


def steps(text):
    """[{"heading": str} | {"n": int, "text": str}, ...] for the recipe page."""
    out, n = [], 0
    for lines in _chunks(text):
        marked = bool(_MARKER.match(lines[0]))
        body = "\n".join([_MARKER.sub("", lines[0], count=1)] + lines[1:]).strip()
        if not body:
            continue
        if not marked and "\n" not in body and len(body) <= 60 and body.endswith(":"):
            out.append({"heading": body[:-1].strip()})
        else:
            n += 1
            out.append({"n": n, "text": body})
    return out
