"""Bash guard: split a command into segments, normalise each and match gates/bash_rules.json."""

from __future__ import annotations

import os
import re
import shlex
from typing import List, Optional, Tuple

OPERATORS = {";", "&&", "||", "|", "&", "\n", "|&", ";;", "(", ")"}
GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
MESSAGE_FLAGS = {("git", "commit"): {"-m", "--message"}, ("git", "tag"): {"-m", "--message"},
                 ("gh", "pr"): {"-b", "--body", "-t", "--title"}, ("gh", "issue"): {"-b", "--body", "-t", "--title"}}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
MAX_DEPTH = 4
WRAPPERS = {"sudo": {"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D"}, "doas": {"-u", "-C"},
            "env": {"-u", "-C", "-S", "--unset", "--chdir"}, "command": set(), "exec": {"-a"}, "nohup": set(),
            "time": {"-f", "-o"}, "xargs": {"-n", "-I", "-L", "-P", "-d", "-E", "-s", "-a"},
            "timeout": {"-s", "-k", "--signal", "--kill-after"}, "nice": {"-n"}, "ionice": {"-c", "-n", "-p"},
            "stdbuf": {"-i", "-o", "-e"}, "chronic": set(), "unbuffer": set(), "caffeinate": {"-w", "-t"}}
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _risky(value: str) -> bool:
    """Return whether a message value would be expanded or executed by the shell."""
    return any(token in value for token in ("$", "`", "<(", ">("))


def tokens(command: str) -> Optional[List[str]]:
    """Lex a command with shell punctuation, or None when it cannot be parsed."""
    try:
        lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def split_heredocs(command: str) -> Tuple[str, List[str]]:
    """Return the command without heredoc bodies and the list of bodies."""
    lines = command.split("\n")
    kept: List[str] = []
    bodies: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for match in HEREDOC.finditer(line):
            body: List[str] = []
            while i < len(lines) and lines[i].lstrip("\t") != match.group(2):
                body.append(lines[i])
                i += 1
            i += 1
            bodies.append("\n".join(body))
    return "\n".join(kept), bodies


def segments(command: str, depth: int = 0) -> Optional[List[List[str]]]:
    """Split into normalised segments; drop heredoc bodies; unwrap wrappers, 'sh -c' and eval recursively."""
    command = split_heredocs(command)[0]
    toks = tokens(HEREDOC.sub(" ", command))
    if toks is None or "<<" in HEREDOC.sub(" ", command).replace("<<<", ""):
        return None
    out: List[List[str]] = []
    current: List[str] = []
    for tok in toks + [";"]:
        if tok in OPERATORS or (tok and set(tok) <= set(";&|()")):
            if current:
                nested = _unwrap(current, depth)
                if nested is None:
                    return None
                out.extend(nested)
            current = []
        else:
            current.append(tok)
    return out


def _unwrap(seg: List[str], depth: int) -> Optional[List[List[str]]]:
    """Normalise one segment and unwrap shell -c and eval."""
    seg = _strip_env(seg)
    if not seg:
        return []
    seg = [os.path.basename(seg[0])] + seg[1:]
    if seg[0] in WRAPPERS and len(seg) > 1:
        rest = _skip_wrapper(seg[0], seg[1:])
        return _unwrap(rest, depth) if rest else []
    if seg[0] in SHELLS and "-c" in seg:
        idx = seg.index("-c")
        if idx + 1 < len(seg) and depth < MAX_DEPTH:
            return segments(seg[idx + 1], depth + 1)
        return None
    if seg[0] == "eval" and depth < MAX_DEPTH:
        return segments(" ".join(seg[1:]), depth + 1)
    if seg[0] == "git":
        seg = _strip_git_globals(seg)
    return [_mask_message(seg)]


def _skip_wrapper(prog: str, args: List[str]) -> List[str]:
    """Drop a wrapper's own options (and env assignments, a timeout duration) to reach the wrapped command."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if prog == "env" and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", arg):
            i += 1
            continue
        if not arg.startswith("-") or arg == "-":
            break
        i += 2 if arg in WRAPPERS[prog] else 1
    if prog == "timeout" and i < len(args):
        i += 1
    return args[i:]


def _strip_env(seg: List[str]) -> List[str]:
    """Drop leading VAR=value assignments."""
    i = 0
    while i < len(seg) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]):
        i += 1
    return seg[i:]


def _strip_git_globals(seg: List[str]) -> List[str]:
    """Remove git global options before the subcommand."""
    out = ["git"]
    i = 1
    while i < len(seg) and seg[i].startswith("-"):
        flag = seg[i].split("=", 1)[0]
        i += 2 if flag in GIT_GLOBAL_WITH_ARG and "=" not in seg[i] else 1
    return out + seg[i:]


def _mask_message(seg: List[str]) -> List[str]:
    """Replace a commit or PR message value with a placeholder when it holds no substitution."""
    if len(seg) < 2:
        return seg
    flags = MESSAGE_FLAGS.get((seg[0], seg[1]))
    if not flags:
        return seg
    out = list(seg)
    for i, tok in enumerate(seg[:-1]):
        if tok in flags and not _risky(seg[i + 1]):
            out[i + 1] = "MESSAGE"
    return out


def match(command: str, rules: List[dict]) -> List[Tuple[str, str]]:
    """Return (rule id, message) for every rule a command breaks; unparsable input is checked as full text."""
    segs = segments(command)
    pieces = [p.strip() for p in re.split(r"[;&|\n()`]+|\$\(", split_heredocs(command)[0])]
    texts = [" ".join(s) for s in segs] if segs is not None else [p for p in pieces if p]
    hits = raw_match(command, [r for r in rules if r.get("scope") == "raw"])
    for rule in (r for r in rules if r.get("scope") != "raw"):
        pattern = re.compile(rule["pattern"])
        if any(pattern.search(t) for t in texts):
            hits.append((rule["id"], rule["message"]))
    return hits


REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
ALL_ARGS = {"tee", "rm", "truncate", "chmod", "chown", "touch", "mv", "unlink", "shred", "unzip", "tar", "ex", "ed"}
LAST_ARG = {"cp", "install", "rsync", "ln"}
IN_PLACE = {"sed": ("-i", "--in-place"), "perl": ("-i", "-pi"), "gawk": ("-i",), "awk": ("-i",)}
INLINE = {"python": "-c", "python3": "-c", "node": "-e", "ruby": "-e", "perl": "-e"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh"}
OUTPUT_FLAGS = {"curl": ("-o", "--output"), "wget": ("-O", "--output-document")}


def write_targets(seg: List[str]) -> List[str]:
    """Return the paths a normalised segment writes to (heuristic, layer 3 behind permissions.deny)."""
    targets = [seg[i + 1] for i, tok in enumerate(seg[:-1]) if tok in REDIRECTS]
    if not seg:
        return targets
    prog, args = seg[0], [a for a in seg[1:] if not a.startswith("-")]
    if prog in ALL_ARGS:
        targets += args
    elif prog in LAST_ARG and args:
        targets.append(args[-1])
    elif prog in IN_PLACE and any(a.startswith(IN_PLACE[prog]) or a == "--in-place" for a in seg[1:]):
        targets += args
    if prog in INLINE and INLINE[prog] in seg:
        idx = seg.index(INLINE[prog])
        if idx + 1 < len(seg):
            targets += re.findall(r"[\w./*-]+", seg[idx + 1])
    return targets + _more_targets(prog, seg)


def _more_targets(prog: str, seg: List[str]) -> List[str]:
    """Targets of git rm/mv/checkout/restore, dd of=, curl -o, cp -t, find -delete and similar."""
    out = [a.split("=", 1)[1] for a in seg[1:] if prog == "dd" and a.startswith("of=")]
    out += [seg[i + 1] for i, a in enumerate(seg[:-1]) if a in ("-t", "--target-directory", "-C", "-d")
            and prog in ("cp", "mv", "install", "ln", "tar", "unzip")]
    out += [seg[i + 1] for i, a in enumerate(seg[:-1]) if a in OUTPUT_FLAGS.get(prog, ())]
    if prog == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-fprint") for a in seg):
        out += [seg[i + 1] for i, a in enumerate(seg[:-1]) if a in ("-name", "-path", "-wholename", "-iname")]
        out += [a for a in seg[1:] if not a.startswith("-")][:1]
    if prog == "git" and len(seg) > 1 and seg[1] in ("rm", "mv"):
        out += [a for a in seg[2:] if not a.startswith("-")]
    if prog == "git" and len(seg) > 2 and seg[1] in ("checkout", "restore") and _foreign_source(seg):
        out += seg[seg.index("--") + 1:] if "--" in seg else [a for a in seg[3:] if not a.startswith("-")]
    return out


def _foreign_source(seg: List[str]) -> bool:
    """Return whether git checkout/restore takes content from a ref other than HEAD or the index."""
    if seg[1] == "restore":
        for i, arg in enumerate(seg):
            value = arg.split("=", 1)[1] if arg.startswith("--source=") else seg[i + 1] if arg in ("-s", "--source") and i + 1 < len(seg) else None
            if value is not None:
                return value not in ("HEAD", "@")
        return False
    before = seg[2:seg.index("--")] if "--" in seg else seg[2:3]
    return any(not a.startswith("-") and a not in ("HEAD", "@") for a in before)


def patch_inputs(seg: List[str]) -> List[str]:
    """Return the patch files that git apply, git am or patch read."""
    if seg[:2] in (["git", "apply"], ["git", "am"]):
        return [a for a in seg[2:] if not a.startswith("-")]
    if seg and seg[0] == "patch":
        return [seg[i + 1] for i, a in enumerate(seg[:-1]) if a in ("-i", "--input", "<")]
    return []


def script_inputs(seg: List[str]) -> List[str]:
    """Return script files an interpreter runs (python3 tool.py, node x.js, bash x.sh)."""
    if not seg or seg[0] not in INTERPRETERS or any(a in seg for a in ("-c", "-e", "-m")):
        return []
    args = [a for a in seg[1:] if not a.startswith("-")]
    return args[:1]


def raw_match(command: str, rules: List[dict]) -> List[Tuple[str, str]]:
    """Return hits of rules that apply to the raw command text (pipes, secrets)."""
    return [(r["id"], r["message"]) for r in rules if re.search(r["pattern"], command)]
