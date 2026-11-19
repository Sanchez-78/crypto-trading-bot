"""Apply a reviewed text change to the exact server bytes, preserving every unchanged line's EOL.

Some live files use CRLF (paper_trade_executor.py) or mixed endings (dashboard_web.py). Writing the
whole file as LF would change line endings outside the reviewed diff. Unchanged lines are copied
byte-for-byte from the server; inserted/replaced lines take the EOL of the server line they follow
(or the file's dominant EOL at the start).
"""
import difflib


def _split(raw: bytes):
    lines = raw.decode("utf-8").splitlines(keepends=True)
    body = [l.rstrip("\r\n") for l in lines]
    eols = [l[len(b):] for l, b in zip(lines, body)]
    return body, eols


def apply_preserving_eol(server: bytes, target_text: str) -> bytes:
    s_body, s_eol = _split(server)
    t_body = target_text.replace("\r\n", "\n").split("\n")
    if t_body and t_body[-1] == "":
        t_body.pop()
    dominant = max(set(s_eol), key=s_eol.count) if s_eol else "\n"
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, s_body, t_body, autojunk=False).get_opcodes():
        if op == "equal":
            out += [s_body[i] + s_eol[i] for i in range(i1, i2)]
        elif j2 > j1:
            eol = s_eol[i1 - 1] if i1 > 0 else dominant
            out += [t_body[j] + (eol or dominant) for j in range(j1, j2)]
    # keep the server's (missing) final newline behaviour
    if out and server and not server.endswith(b"\n"):
        out[-1] = out[-1].rstrip("\r\n")
    return "".join(out).encode("utf-8")


def changed_lines(server: bytes, artifact: bytes):
    """(+/-) change lines on content, and whether every unchanged line kept its exact bytes."""
    s_body, s_eol = _split(server)
    a_body, a_eol = _split(artifact)
    changes, eol_kept = [], True
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, s_body, a_body, autojunk=False).get_opcodes():
        if op == "equal":
            eol_kept &= all(s_eol[i1 + k] == a_eol[j1 + k] for k in range(i2 - i1))
        else:
            changes += ["-" + s_body[i] for i in range(i1, i2)] + ["+" + a_body[j] for j in range(j1, j2)]
    return changes, eol_kept
