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
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done", "esac"}
MAX_DEPTH = 4
WRAPPERS = {"sudo": {"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D"}, "doas": {"-u", "-C"},
            "env": {"-u", "-C", "-S", "--unset", "--chdir"}, "command": set(), "exec": {"-a"}, "nohup": set(),
            "time": {"-f", "-o"}, "xargs": {"-n", "-I", "-L", "-P", "-d", "-E", "-s", "-a"},
            "timeout": {"-s", "-k", "--signal", "--kill-after"}, "nice": {"-n"}, "ionice": {"-c", "-n", "-p"},
            "stdbuf": {"-i", "-o", "-e"}, "chronic": set(), "unbuffer": set(), "caffeinate": {"-w", "-t"}}
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
PUNCTUATION = ";&|()<>"
PLACEHOLDER = {c: chr(0xE000 + i) for i, c in enumerate(PUNCTUATION)}
RAW = {v: k for k, v in PLACEHOLDER.items()}
COMMENT_START = " \t\n;&|()"


def _risky(value: str) -> bool:
    """Return whether a message value would be expanded or executed by the shell."""
    return any(token in value for token in ("$", "`", "<(", ">("))


def _protect(command: str, comments: bool = False) -> str:
    """Replace quoted or escaped shell punctuation by placeholders and unquoted newlines by ';'.

    comments=True drops shell comments (a word that starts with '#' up to the end of its line); only script
    files get that, because a command typed into an interactive shell may not treat '#' as a comment.
    """
    out: List[str] = []
    quote = ""
    i = 0
    while i < len(command):
        c = command[i]
        nxt = command[i + 1] if i + 1 < len(command) else ""
        if not quote and c == "\\" and nxt:
            out.append(" " if nxt == "\n" else PLACEHOLDER.get(nxt, c + nxt))
            i += 2
            continue
        if quote == '"' and c == "\\" and nxt:
            out.append(c + PLACEHOLDER.get(nxt, nxt))
            i += 2
            continue
        if comments and not quote and c == "#" and (i == 0 or command[i - 1] in COMMENT_START):
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
            continue
        if not quote and c in "'\"":
            quote = c
        elif quote and c == quote:
            quote = ""
        elif not quote and c == "\n":
            c = " ; "
        elif quote and c in PLACEHOLDER:
            c = PLACEHOLDER[c]
        out.append(c)
        i += 1
    return "".join(out)


def raw(token: str) -> str:
    """Return a token with quoted punctuation placeholders turned back into the characters the shell sees."""
    return "".join(RAW.get(c, c) for c in token)


def uncommented(script: str) -> str:
    """Return a shell script text without its comments, with quoted text kept and line ends as ' ; '."""
    return raw(_protect(script, comments=True))


def tokens(command: str, comments: bool = False) -> Optional[List[str]]:
    """Lex a command with shell punctuation, or None when it cannot be parsed.

    Quoted punctuation never becomes an operator: a token made only of quoted punctuation keeps its
    placeholders (so grep '>' x has no redirect), every other token gets its characters back.
    """
    try:
        lexer = shlex.shlex(_protect(command, comments), posix=True, punctuation_chars=PUNCTUATION)
        lexer.whitespace_split = True
        lexer.commenters = ""
        toks = list(lexer)
    except ValueError:
        return None
    return [t if t and set(t) <= set(RAW) else raw(t) for t in toks]


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


def segments(command: str, depth: int = 0, comments: bool = False) -> Optional[List[List[str]]]:
    """Split into normalised segments; drop heredoc bodies; unwrap wrappers, 'sh -c' and eval recursively."""
    command = HEREDOC.sub(" ", split_heredocs(command)[0])
    toks = tokens(command, comments)
    if toks is None or "<<" in _protect(command, comments).replace("<<<", ""):
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
    """Normalise one segment: drop shell keywords and env assignments, unwrap wrappers, shell -c and eval."""
    while seg and seg[0] in KEYWORDS:
        seg = seg[1:]
    seg = _strip_env(seg)
    if not seg:
        return []
    seg = [os.path.basename(seg[0])] + seg[1:]
    if seg[0] in KEYWORDS:
        return _unwrap(seg, depth)
    if seg[0] in WRAPPERS and len(seg) > 1:
        rest = _skip_wrapper(seg[0], seg[1:])
        return _unwrap(rest, depth) if rest else []
    command_flag = [i for i, a in enumerate(seg) if i and re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a)]
    if seg[0] in SHELLS and command_flag:
        idx = command_flag[0]
        if idx + 1 < len(seg) and depth < MAX_DEPTH:
            return segments(raw(seg[idx + 1]), depth + 1)
        return None
    if seg[0] == "eval" and depth < MAX_DEPTH:
        return segments(" ".join(raw(t) for t in seg[1:]), depth + 1)
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


GH_API_VALUE_SHORT = "HfFXpqt"
GH_API_BOOL_SHORT = "i"
GH_API_VALUE_LONG = {"--header", "--field", "--raw-field", "--method", "--preview", "--jq", "--template", "--input",
                     "--hostname", "--cache"}
GH_API_BOOL_LONG = {"--paginate", "--slurp", "--include", "--silent", "--verbose"}


def gh_api_fields(seg: List[str]) -> bool:
    """Return whether a gh api segment sends fields without its own tokens saying exactly GET (fields mean POST).

    Each flag is read the way gh reads it: a value flag takes the rest of its token or the next token, so text
    inside a field value (`-f "body=-X GET"`) never counts as a method. Unknown flags, any method token other
    than exactly GET and the graphql endpoint keep the fields red.
    """
    if seg[:2] != ["gh", "api"]:
        return False
    fields, unknown, methods, positional = False, False, [], []
    args = seg[2:]
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            positional += args[i:]
            break
        if arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if name in GH_API_VALUE_LONG:
                if not eq:
                    value = args[i] if i < len(args) else ""
                    i += 1
                fields = fields or name in ("--field", "--raw-field")
                if name == "--method":
                    methods.append(value)
            elif name not in GH_API_BOOL_LONG or eq:
                unknown = True
            continue
        if arg.startswith("-") and len(arg) > 1:
            for j, letter in enumerate(arg[1:], 1):
                if letter in GH_API_VALUE_SHORT:
                    value = arg[j + 1:]
                    if not value:
                        value = args[i] if i < len(args) else ""
                        i += 1
                    fields = fields or letter in "fF"
                    if letter == "X":
                        methods.append(value)
                    break
                if letter not in GH_API_BOOL_SHORT:
                    unknown = True
                    break
            continue
        positional.append(arg)
    if not fields:
        return False
    return unknown or not methods or any(m != "GET" for m in methods) or "graphql" in positional


TOKEN_CHECKS = {"gh_api_fields": gh_api_fields}


def match(command: str, rules: List[dict]) -> List[Tuple[str, str]]:
    """Return (rule id, message) for every rule a command breaks; unparsable input is checked as full text.

    A rule with scope "tokens" names a check in TOKEN_CHECKS that reads each normalised segment's token list;
    its "pattern" applies to the text only for input that cannot be split into segments (fail-closed).
    """
    segs = segments(command)
    pieces = [p.strip() for p in re.split(r"[;&|\n()`]+|\$\(", split_heredocs(command)[0])]
    texts = [raw(" ".join(s)) for s in segs] if segs is not None else [p for p in pieces if p]
    hits = raw_match(command, [r for r in rules if r.get("scope") == "raw"])
    for rule in (r for r in rules if r.get("scope") not in ("raw", "tokens")):
        pattern = re.compile(rule["pattern"])
        if any(pattern.search(t) for t in texts):
            hits.append((rule["id"], rule["message"]))
    for rule in (r for r in rules if r.get("scope") == "tokens"):
        check = TOKEN_CHECKS[rule["check"]]
        if (any(check(s) for s in segs) if segs is not None
                else any(re.search(rule["pattern"], t) for t in texts)):
            hits.append((rule["id"], rule["message"]))
    return hits


REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
ALL_ARGS = {"tee", "rm", "truncate", "chmod", "chown", "touch", "mv", "unlink", "shred", "unzip", "tar", "ex", "ed"}
LAST_ARG = {"cp", "install", "rsync", "ln"}
IN_PLACE = {"sed": ("-i", "--in-place"), "perl": ("-i", "-pi"), "gawk": ("-i",), "awk": ("-i",)}
INLINE_LETTERS = {"python": "c", "python3": "c", "ruby": "e", "perl": "eE"}
NODE_INLINE = ("-e", "--eval", "-p", "--print")
PYTHON_VALUE_LETTERS = "WX"
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh"}
OUTPUT_FLAGS = {"curl": ("-o", "--output"), "wget": ("-O", "--output-document")}


def write_targets(seg: List[str]) -> List[str]:
    """Return the paths a normalised segment writes to (heuristic, layer 3 behind permissions.deny).

    Inline interpreter code (python3 -c, node -e) is not a list of targets; inline_code() hands it to the
    caller, which blocks a control path unless every mention of it is a proven read.
    """
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
    return targets + _more_targets(prog, seg)


def inline_code(seg: List[str]) -> List[str]:
    """Return the inline programs of an interpreter segment: -c of python, -e of ruby and perl (also inside
    combined flags such as -Ic or -ne), -e/-p/--eval/--print of node."""
    if seg:
        seg = [re.sub(r"^(python3?)\.\d+$", r"\1", seg[0])] + seg[1:]
    if not seg or seg[0] not in INLINE_LETTERS and seg[0] != "node":
        return []
    out: List[str] = []
    i = 1
    while i < len(seg):
        arg, nxt = seg[i], seg[i + 1] if i + 1 < len(seg) else None
        if seg[0] == "node":
            if arg in NODE_INLINE and nxt is not None:
                out.append(nxt)
                i += 1
            elif arg.split("=", 1)[0] in ("--eval", "--print") and "=" in arg:
                out.append(arg.split("=", 1)[1])
        elif arg.startswith("-") and not arg.startswith("--") and len(arg) > 1:
            letters = arg[1:]
            hit = next((k for k, ch in enumerate(letters) if ch in INLINE_LETTERS[seg[0]]), None)
            if hit is not None:
                rest = letters[hit + 1:]
                if rest:
                    out.append(rest)
                elif nxt is not None:
                    out.append(nxt)
                    i += 1
            elif seg[0].startswith("python") and letters[-1] in PYTHON_VALUE_LETTERS:
                i += 1
            elif seg[0].startswith("python") and "m" in letters:
                break
        elif not arg.startswith("-") and seg[0].startswith("python"):
            break
        i += 1
    return out


READ_CALLS = (
    (re.compile(r"(?:(?<![\w.])|\bio\.|\bcodecs\.)open\(\s*$"),
     re.compile(r"^\s*(?:,\s*(?:mode\s*=\s*)?(['\"])[rbtU]*\1)?(?:\s*,\s*(?:encoding|errors)\s*=\s*(['\"])[\w.-]*\2)*\s*\)"),
     True),
    (re.compile(r"(?<![\w.])(?:pathlib\.)?(?:Pure)?(?:Posix)?Path\(\s*$"),
     re.compile(r"^\s*\)\s*\.\s*(?:read_text|read_bytes|exists|is_file|is_dir|stat)\("), False),
    (re.compile(r"\bos\.path\.(?:exists|lexists|isfile|isdir|getsize|getmtime)\(\s*$"), re.compile(r"^\s*\)"), False),
    (re.compile(r"\b(?:readFileSync|readFile)\(\s*$"),
     re.compile(r"^\s*(?:,\s*(?:(['\"])[\w-]+\1|\{\s*encoding\s*:\s*(['\"])[\w-]+\2\s*\}))?\s*\)"), False),
    (re.compile(r"\b(?:existsSync|statSync|lstatSync)\(\s*$"), re.compile(r"^\s*\)"), False),
    (re.compile(r"\b(?:File\.(?:read|readlines|exist\?|file\?|size)|IO\.(?:read|readlines))\(\s*$"),
     re.compile(r"^\s*\)"), False),
)
HANDLE_ESCAPE = re.compile(r"\.name\b|getattr|fileno|fdopen|/dev/fd|/proc/|__dict__|\bvars\(")
CALLEES = r"open|Path|PurePath|PosixPath|PurePosixPath|readFileSync|readFile|existsSync|statSync|lstatSync|io|codecs|os|pathlib|fs|File|IO"
ATTRS = r"exists|lexists|isfile|isdir|getsize|getmtime|read_text|read_bytes|is_file|is_dir|stat|read|readlines|size|path"
SHADOW = re.compile(
    rf"(?<![\w.])(?:{CALLEES})\s*:?=(?!=)|\.(?:{ATTRS}|{CALLEES})\s*=(?!=)|\bas\s+(?:{CALLEES})\b"
    rf"|\b(?:def|class|function|let|var|const)\s+(?:{CALLEES})\b|[{{,]\s*\w+\s*:\s*(?:{CALLEES})\s*[,}}]"
    rf"|[(,]\s*(?:{CALLEES})\s*[,)]"
    r"|builtins|globals\s*\(|locals\s*\(|setattr|__dict__|\bexec\b|\beval\b|\bcompile\s*\(|__import__|importlib"
    r"|\bFunction\s*\(|\bvm\.|prototype|defineProperty|Reflect\.|Object\.assign|define_method|instance_eval|class_eval")
CANONICAL_REQUIRE = re.compile(r"\b(?:const|let|var)\s+fs\s*=\s*require\(\s*(['\"])(?:node:)?fs\1\s*\)")


def read_position(code: str, start: int, end: int) -> bool:
    """Return whether code[start:end] is a whole string literal that only a known read call consumes.

    Accepted: open(p) and open(p, 'r'/'rb', encoding=...), Path(p).read_text()/exists(), os.path.exists(p),
    readFileSync(p[, 'utf8']), existsSync(p), File.read(p). A file handle from open() counts only when the
    code never reaches the handle's path (.name, getattr, fileno, fdopen, /proc, /dev/fd). No read counts when
    the code may rebind a read call (open = ..., import x as open, exec, eval, builtins, setattr and similar).
    """
    quote = code[start - 1] if start > 0 else ""
    if quote not in ("'", '"', "`") or code[end:end + 1] != quote or (quote == "`" and "${" in code[start:end]):
        return False
    if SHADOW.search(CANONICAL_REQUIRE.sub(" ", code)):
        return False
    before, after = code[:start - 1], code[end + 1:]
    if re.search(r"(?<![\w])[rRbBuU]$", before):
        before = before[:-1]
    for head, tail, handle in READ_CALLS:
        if head.search(before) and tail.match(after) and not (handle and HANDLE_ESCAPE.search(code)):
            return True
    return False


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
    if not seg or seg[0] not in INTERPRETERS or inline_code(seg) or any(a in seg for a in ("-c", "-e", "-m")):
        return []
    values = {"-o", "+o", "-O", "+O"} if seg[0] in SHELLS else set()
    args = [a for i, a in enumerate(seg[1:], 1) if not a.startswith(("-", "+") if values else "-")
            and seg[i - 1] not in values]
    return args[:1]


def noexec(seg: List[str]) -> bool:
    """Return whether a shell segment only reads its script (bash -n x.sh, also inside combined flags like -nv)."""
    if not seg or seg[0] not in SHELLS:
        return False
    for arg in seg[1:]:
        if not arg.startswith("-") or arg == "-" or arg == "--":
            return False
        if not arg.startswith("--") and "c" in arg[1:]:
            return False
        if not arg.startswith("--") and "n" in arg[1:]:
            return True
    return False


PUSH_VALUE_FLAGS = ("-o", "--push-option", "--repo", "--receive-pack", "--exec")


def push_refspecs(seg: List[str]) -> Optional[Tuple[List[str], bool]]:
    """Return the refspecs of a git push segment and whether --delete is set; None for any other segment."""
    if seg[:2] != ["git", "push"]:
        return None
    args = seg[2:]
    positional = [a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] not in PUSH_VALUE_FLAGS)]
    delete = any(a in ("-d", "--delete") for a in args)
    return positional[1:], delete


def raw_match(command: str, rules: List[dict]) -> List[Tuple[str, str]]:
    """Return hits of rules that apply to the raw command text (pipes, secrets)."""
    return [(r["id"], r["message"]) for r in rules if re.search(r["pattern"], command)]
