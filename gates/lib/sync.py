"""Generate settings.json, path-bound rules, CODEOWNERS, the protect workflow and rule notes from the data files."""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List

from . import catalog as catalog_mod
from . import gitx
from . import roles as roles_mod
from .findings import Finding

RC = ('rc=$?; [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ] || { echo "[gates] gate.py ended with exit $rc; '
      'blocked as a precaution" >&2; rc=2; }; exit $rc')
WRAP = ('f="$CLAUDE_PROJECT_DIR/gates/gate.py"; if [ -f "$f" ] && command -v python3 >/dev/null 2>&1; '
        'then python3 -I "$f" hook {event}; ' + RC + '; else echo "[gates] gates/gate.py or python3 missing; '
        'blocked as a precaution" >&2; exit 2; fi')
SHORT = ('f="$CLAUDE_PROJECT_DIR/gates/gate.py"; [ -f "$f" ] && command -v python3 >/dev/null 2>&1 '
         '&& exec python3 -I "$f" hook {event}; exit 0')
VERIFIED = ('p=$(cat); d="$CLAUDE_PROJECT_DIR"; f="$d/gates/gate.py"; '
            'if [ ! -f "$f" ] || ! command -v python3 >/dev/null 2>&1; '
            'then echo "[gates] gates/gate.py or python3 missing; blocked as a precaution" >&2; exit 2; fi; '
            'r=$(git -C "$d" rev-parse -q --verify "{ref}^{commit}" 2>/dev/null '
            '|| git -C "$d" rev-parse -q --verify "refs/gates/baseline^{commit}" 2>/dev/null '
            '|| git -C "$d" rev-parse -q --verify "HEAD^{commit}" 2>/dev/null); bad=""; '
            'if [ -z "$r" ]; then bad=" (no commit)"; '
            'echo "[gates] [GATES-BASELINE] no commit to verify the gate code against" >&2; else '
            'for g in $( (git -C "$d" ls-tree -r --name-only "$r" -- gates/gate.py gates/lib; '
            'cd "$d" && ls gates/gate.py gates/lib/*.py) 2>/dev/null | sort -u); do '
            '[ "$(git -C "$d" hash-object --no-filters "$d/$g" 2>/dev/null)" = '
            '"$(git -C "$d" rev-parse -q --verify "$r:$g" 2>/dev/null)" ] '
            '|| { bad="$bad $g"; echo "[gates] [GATES-CONTROLS] $g differs from $r; the gate code must match the '
            'reference" >&2; }; done; fi; '
            'if [ -n "$bad" ]; then {release}exit 2; fi; '
            'printf \'%s\' "$p" | python3 -I -X pycache_prefix=/dev/null/gates "$f" hook {event}; ' + RC)
RELEASE = ('gd=$(git -C "$d" rev-parse --absolute-git-dir 2>/dev/null) && mkdir -p "$gd/gates" '
           '&& { cp "$gd/index" "$gd/gates/wrapper-index" 2>/dev/null; '
           't=$(GIT_INDEX_FILE="$gd/gates/wrapper-index" git -C "$d" add -A 2>/dev/null '
           '&& GIT_INDEX_FILE="$gd/gates/wrapper-index" git -C "$d" write-tree 2>/dev/null); }; '
           'h="$t$bad"; case "$p" in *\'"stop_hook_active": true\'*|*\'"stop_hook_active":true\'*) '
           'if [ -n "$t" ] && [ "$(cat "$gd/gates/wrapper-red-{event}" 2>/dev/null)" = "$h" ]; then '
           'echo \'{"systemMessage": "gates: the gate code differs from the reference or has none and the agent '
           'stopped again without any change; stop released, the operator decides"}\'; exit 0; fi;; esac; '
           '[ -z "$t" ] || printf \'%s\' "$h" > "$gd/gates/wrapper-red-{event}"; ')
FLOWKIT = ('p=$(cat); b="$CLAUDE_PROJECT_DIR/.claude/hooks/pretooluse-blocker.sh"; '
           'if [ -x "$b" ]; then printf \'%s\' "$p" | "$b" || exit 2; '
           'else echo "[gates] flowkit blocker missing; blocked as a precaution" >&2; exit 2; fi; '
           'f="$CLAUDE_PROJECT_DIR/gates/gate.py"; if [ -f "$f" ] && command -v python3 >/dev/null 2>&1; '
           'then printf \'%s\' "$p" | python3 -I "$f" hook pre-bash; ' + RC + '; '
           'else echo "[gates] gates/gate.py or python3 missing; blocked as a precaution" >&2; exit 2; fi')
FLOWKIT_BLOCKER = ".claude/hooks/pretooluse-blocker.sh"
PRIVATE_READS = ["Read(**/.env)", "Read(**/.env.*)", "Read(**/*credentials*)", "Read(**/secrets*)"]


def _load(tree: str, rel: str) -> dict:
    """Load a JSON data file."""
    with open(os.path.join(tree, rel), encoding="utf-8") as handle:
        return json.load(handle)


def _cmd(template: str, event: str, **extra: object) -> dict:
    """Return one command hook."""
    hook: Dict[str, object] = {"type": "command", "command": template.replace("{event}", event)}
    hook.update(extra)
    return hook


def deny_rules(tree: str) -> List[str]:
    """Return the deny list: Edit(...) for every operator-only glob plus private reads."""
    controls = _load(tree, "gates/controls.json")
    return [f"Edit({g})" for g in controls["operator_only"]] + PRIVATE_READS


STACK_COMMANDS = ["docker compose *", "make up", "make down", "make db-schema", "make db-check"]


def sandbox_paths(tree: str) -> List[str]:
    """Return concrete denyWrite paths: plain entries always (a file Claude Code creates later must not change
    the rendered settings), glob patterns as the files they match today (Linux skips entries with wildcards)."""
    out = set()
    for pattern in _load(tree, "gates/controls.json")["operator_only"]:
        head = pattern[:-3] if pattern.endswith("/**") else pattern
        if not any(c in head for c in "*?["):
            out.add(head)
        else:
            out |= set(gitx.ls(tree, [pattern]))
    return sorted(f"./{p}" for p in out)


def sandbox(tree: str, project: dict) -> Dict[str, object]:
    """Return the sandbox block for question 11 = yes: on, concrete denyWrite paths, stack commands outside."""
    block: Dict[str, object] = {"enabled": True, "filesystem": {"denyWrite": sandbox_paths(tree)}}
    if os.path.isfile(os.path.join(tree, "compose.yaml")):
        block["excludedCommands"] = STACK_COMMANDS
    return block


def verified(event: str, default_branch: str) -> str:
    """Return the wrapper that checks gates/gate.py and gates/lib against the reference commit before it runs."""
    release = RELEASE if event in ("stop", "subagent-stop") else ""
    return (VERIFIED.replace("{release}", release).replace("{ref}", f"origin/{default_branch}")
            .replace("{event}", event))


def settings(tree: str) -> str:
    """Render .claude/settings.json; path rules use Edit(...) only, Write(...) path rules are never consulted."""
    project = _load(tree, "gates/project.json")
    branch = project.get("default_branch", "main")
    chained = project.get("flowkit") and os.path.isfile(os.path.join(tree, FLOWKIT_BLOCKER))
    pre_bash = _cmd(FLOWKIT, "pre-bash", timeout=40) if chained else _cmd(WRAP, "pre-bash", timeout=30)
    hooks = {
        "SessionStart": [{"matcher": "startup|resume|clear|compact",
                          "hooks": [_cmd(SHORT, "session-start", timeout=10)]}],
        "SubagentStart": [{"hooks": [_cmd(SHORT, "subagent-start", timeout=10)]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [pre_bash]},
                       {"matcher": "Edit|Write|MultiEdit", "hooks": [_cmd(WRAP, "pre-write", timeout=30)]}],
        "PostToolUse": [{"matcher": "Edit|Write|MultiEdit",
                         "hooks": [_cmd(SHORT, "post-edit", timeout=30, statusMessage="gates: format and rules")]}],
        "PostToolBatch": [{"hooks": [_cmd(SHORT, "post-batch", timeout=60)]}],
        "Stop": [{"hooks": [{"type": "command", "command": verified("stop", branch), "timeout": 180}]}],
        "SubagentStop": [{"hooks": [{"type": "command", "command": verified("subagent-stop", branch), "timeout": 180}]}],
        "ConfigChange": [{"matcher": "project_settings|local_settings|skills",
                          "hooks": [{"type": "command", "command": verified("config-change", branch), "timeout": 60}]}],
    }
    data: Dict[str, object] = {"permissions": {"deny": deny_rules(tree)}, "hooks": hooks}
    if project.get("sandbox"):
        data["sandbox"] = sandbox(tree, project)
    for key, value in sorted(project.get("extra_settings", {}).items()):
        data[key] = value
    return json.dumps(data, indent=2) + "\n"


def rules_md(tree: str) -> Dict[str, str]:
    """Render .claude/rules/<component>-<role>.md with paths: frontmatter from roles.json."""
    cfg = roles_mod.load(tree)
    entries = catalog_mod.load(tree)
    out = {}
    for component in sorted(cfg["components"]):
        for role in sorted(cfg["components"][component]["roles"]):
            bound = [e for e in entries if catalog_mod.applies(e, component, role) and e.get("agents_md")
                     and e.get("component", "*") != "*"]
            if not bound:
                continue
            globs = roles_mod.patterns(cfg, component, role)
            lines = ["---", "paths:"] + [f'  - "{g}"' for g in globs] + [
                "---", "", f"# {component} / {role}", "",
                "Generated by `make sync` from gates/catalog.json. Do not edit.", ""]
            lines += [f"- {e['agents_md']} [{e['id']}]" for e in bound][:30]
            out[f".claude/rules/{component}-{role}.md"] = "\n".join(lines) + "\n"
    return out


def _codeowners_glob(glob: str) -> str:
    """Translate a controls glob into a CODEOWNERS pattern."""
    if glob.endswith("/**"):
        return "/" + glob[:-2]
    return glob if glob.startswith("**/") else "/" + glob


def codeowners(tree: str) -> Dict[str, str]:
    """Render .github/CODEOWNERS when an operator login is known."""
    login = _load(tree, "gates/project.json").get("operator_login", "")
    if not login:
        return {}
    globs = _load(tree, "gates/controls.json")["operator_only"]
    lines = ["# Generated by `make sync` from gates/controls.json."]
    lines += [f"{_codeowners_glob(g)} @{login}" for g in globs]
    return {".github/CODEOWNERS": "\n".join(lines) + "\n"}


def protect_workflow(tree: str) -> Dict[str, str]:
    """Render the protect-operator-files workflow with the control globs embedded."""
    if not _load(tree, "gates/project.json").get("github"):
        return {}
    globs = json.dumps(_load(tree, "gates/controls.json")["operator_only"])
    with open(os.path.join(tree, "gates", "templates", "protect-operator-files.yml"), encoding="utf-8") as handle:
        text = handle.read().replace("__CONTROL_GLOBS__", globs.replace("'", "''"))
    return {".github/workflows/protect-operator-files.yml": text}


def ruleset(tree: str) -> Dict[str, str]:
    """Render gates/ruleset.json for the default branch: the one aggregate check 'gate', 'protect', review by identity."""
    project = _load(tree, "gates/project.json")
    if not project.get("github"):
        return {}
    bot = project.get("agent_identity") == "bot"
    data = {"name": "agent-repo gates", "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                      {"type": "pull_request", "parameters": {
                          "required_approving_review_count": 1 if bot else 0, "require_code_owner_review": bot,
                          "dismiss_stale_reviews_on_push": True, "require_last_push_approval": bot,
                          "required_review_thread_resolution": False}},
                      {"type": "required_status_checks", "parameters": {
                          "strict_required_status_checks_policy": False,
                          "required_status_checks": [{"context": "gate"}, {"context": "protect"}]}}]}
    return {"gates/ruleset.json": json.dumps(data, indent=1) + "\n"}


def rule_notes(tree: str) -> Dict[str, str]:
    """Return rule YAML files whose note field carries the catalog's why and fix."""
    out = {}
    for entry in catalog_mod.load(tree):
        path = os.path.join(tree, entry.get("carrier_ref", ""))
        if entry.get("carrier") != "ast-grep" or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        note = f"Why: {entry['why']}. Fix: {entry['fix']}".replace('"', "'")
        out[entry["carrier_ref"]] = re.sub(r"^note:.*$", lambda _m: f'note: "{note}"', text, count=1,
                                           flags=re.MULTILINE)
    return out


def render_all(tree: str) -> Dict[str, str]:
    """Render every generated file."""
    out = {".claude/settings.json": settings(tree)}
    for part in (rules_md, codeowners, protect_workflow, ruleset, rule_notes):
        out.update(part(tree))
    return out


def _current(path: str) -> object:
    """Return a file's text or None."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(tree: str, only: object = None) -> List[str]:
    """Write generated files that differ (optionally all but settings.json) and return their paths."""
    changed = []
    for rel, text in render_all(tree).items():
        if only == "no-settings" and rel == ".claude/settings.json":
            continue
        path = os.path.join(tree, rel)
        if _current(path) != text:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            changed.append(rel)
    return changed


def check(tree: str) -> List[Finding]:
    """D9: return a finding per generated file that drifted from its sources."""
    return [Finding(rel, 1, "GATES-D9", "generated file drifted; the operator runs `make sync`")
            for rel, text in render_all(tree).items() if _current(os.path.join(tree, rel)) != text]
