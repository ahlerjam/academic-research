"""BASH-CONTROL-WRITE blocks only a control path as a write target: read-only mentions and script runs that only read pass."""

from __future__ import annotations

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import cmdnorm  # noqa: E402

READ_ONLY = (
    "python3 -c \"open('gates/bash_rules.json')\"",
    "python3 -c \"import json;print(json.load(open('gates/bash_rules.json')))\"",
    "python3 -c \"print(open('AGENTS.md', encoding='utf-8').read())\" > out.txt",
    "python3 -c \"open('out.txt','w').write(open('gates/bash_rules.json').read())\"",
    "python3 -c \"from pathlib import Path; print(Path('AGENTS.md').read_text())\"",
    "python3 -c \"import os; print(os.path.exists('gates/bash_rules.json'))\"",
    "node -e \"console.log(require('fs').readFileSync('AGENTS.md','utf8'))\"",
    "node -e \"const fs = require('fs'); console.log(fs.readFileSync('AGENTS.md', 'utf8'))\"",
    "grep -n '>' gates/lib/hooks.py",
    "grep -n \">>\" gates/lib/hooks.py > out.txt",
    "grep -n x gates/bash_rules.json > out.txt",
    "grep -c '|' Makefile",
    "echo x \\> AGENTS.md",
    "cat .node-version",
    "diff Makefile other.mk > out.diff",
    "cp AGENTS.md notes.md",
    "cd gates && grep -n rules bash_rules.json > /tmp/out.txt",
    "rm -rf packages/*/dist",
    "rm -f /tmp/node*",
)
WRITES = (
    "echo x > AGENTS.md",
    "echo x >> Makefile",
    "tee .node-version < /dev/null",
    "cp x.json gates/bash_rules.json",
    "mv x AGENTS.md",
    "install -m 644 x Makefile",
    "sed -i '' 's/a/b/' gates/bash_rules.json",
    "truncate -s 0 AGENTS.md",
    "rm .node-version",
    "ln -sf x AGENTS.md",
    "cd gates && echo '{}' > bash_rules.json",
    "if true; then rm AGENTS.md; fi",
    "{ rm AGENTS.md; }",
    "! rm AGENTS.md",
    "while true; do rm AGENTS.md; done",
    "bash -xc 'rm AGENTS.md'",
    "echo x '>' y > AGENTS.md",
    "eval echo x '>' AGENTS.md",
    "sh -c 'echo x > AGENTS.md'",
    "bash -c \"grep x y; rm -f gates/bash_rules.json\"",
    "grep -n x gates/bash_rules.json > out.txt 'oops",
    "python3 -c \"open('gates/bash_rules.json','w').write('{}')\"",
    "python3 -c \"open('gates/bash_rules.json', mode='w')\"",
    "python3 -c \"open('gates/bash_rules.json', 'r+')\"",
    "python3 -c \"open('gates/bash_rules.json', 'a')\"",
    "python3 -c \"open('gates/bash_rules.json', m); m='w'\"",
    "python3 -c \"import os; f=open('AGENTS.md'); os.remove(f.name)\"",
    "python3 -c \"import os; os.remove(getattr(open('AGENTS.md'), 'name'))\"",
    "python3 -c \"import shutil; shutil.copy('x','AGENTS.md')\"",
    "python3 -c \"import os; open=os.remove; open('AGENTS.md')\"",
    "python3 -c \"from os import remove as open; open('AGENTS.md')\"",
    "python3 -c \"import builtins, os; builtins.open = os.remove; open('AGENTS.md')\"",
    "python3 -c \"exec('op'+'en=__import__(1)'); open('AGENTS.md')\"",
    "python3 -c \"import os; os.remove('gates/bash_rules.json')\"",
    "python3 -c \"from pathlib import Path; Path('AGENTS.md').write_text('x')\"",
    "python3 -c \"p='gates/bash_rules.json'; open(p,'w')\"",
    "python3 -c \"import os; os.system('echo x > AGENTS.md')\"",
    "python3 -c \"import os; os.chdir('gates'); open('bash_rules.json','w')\"",
    "python3 -Ic \"open('gates/bash_rules.json','w').write('{}')\"",
    "python3 -I -c \"open('gates/bash_rules.json','w').write('{}')\"",
    "python3.12 -c \"open('gates/bash_rules.json','w').write('{}')\"",
    "python3 -c \"open(r'gates/bash_rules.json', 'w')\"",
    "node -e \"require('fs').writeFileSync('AGENTS.md','x')\"",
    "node --eval=\"require('fs').unlinkSync('AGENTS.md')\"",
    "node -e \"require('fs').rmSync('AGENTS.md')\"",
    "node -e \"require('fs').readFileSync('AGENTS.md', {flag: 'w+'})\"",
    "node -e \"const {unlinkSync: readFileSync} = require('fs'); readFileSync('AGENTS.md')\"",
    "ruby -e \"File.write('AGENTS.md', 'x')\"",
    "perl -ne \"unlink 'AGENTS.md'\"",
    "python3 -c \"print('AGENTS.md')\"",
    "rm -rf gates/*",
    "rm gates/lib/*.py",
    "echo x > gates/bash_rul*",
    "rm -rf .claude/*",
    "python3 -c \"import glob, os; [os.remove(p) for p in glob.glob('gates/*')]\"",
    "python3 -c \"import os; vars(os.path)['exists']=os.remove; os.path.exists('AGENTS.md')\"",
    "node -e \"const fs=require('fs'); fs['existsSync']=fs.unlinkSync; fs.existsSync('AGENTS.md')\"",
    "echo AGENTS.md | xargs rm",
    "CMD=rm; $CMD AGENTS.md",
    "F=AGENTS.md; rm $F",
)
CLOUD_SETUP = """#!/bin/bash
# constraint: setup script of the Claude Code cloud environment; runs before Claude Code starts and is cached when it stays under about 5 minutes.
set -euo pipefail

repo="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo"

want="$(cat .node-version)"
if [ "$(node --version 2>/dev/null)" != "v$want" ]; then
  curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v$want/node-v$want-linux-x64.tar.xz"
  sudo tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
  rm -f /tmp/node.tar.xz
fi
hash -r
node --version

npm install --global @ast-grep/cli@0.45.3
corepack enable
make setup

if [ -d packages/web/e2e ]; then
  pnpm exec playwright install --with-deps chromium
fi
"""


class HookTree(unittest.TestCase):
    """A temporary tree with the real gates; bash() runs the pre-bash hook and returns its exit code."""

    def setUp(self) -> None:
        self.root = support.make_tree()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def run_bash(self, command: str):
        return support.gate(self.root, ["hook", "pre-bash"], {"tool_input": {"command": command}, "cwd": self.root})

    def bash(self, command: str) -> int:
        return self.run_bash(command).returncode


class ReadOnlyAndWrites(HookTree):
    """A read-only mention of a control path passes; every way of writing one stays blocked."""

    def test_read_only_mentions_pass(self) -> None:
        wrong = [f"{c!r}: {p.stderr.strip()[:160]}" for c in READ_ONLY for p in [self.run_bash(c)] if p.returncode != 0]
        self.assertEqual(wrong, [])

    def test_writes_stay_blocked_as_control_writes(self) -> None:
        wrong = []
        for command in WRITES:
            proc = self.run_bash(command)
            if proc.returncode != 2 or "BASH-CONTROL-WRITE" not in proc.stderr:
                wrong.append(f"{command!r} -> {proc.returncode} {proc.stderr.strip()[:120]}")
        self.assertEqual(wrong, [])


class ShellScripts(HookTree):
    """A shell script is parsed like a typed command: only a control path as write target blocks."""

    def test_cloud_setup_script_runs_and_syntax_checks(self) -> None:
        support.write(self.root, "docs/autonomy/cloud-setup.sh", CLOUD_SETUP)
        for command in ("bash -n docs/autonomy/cloud-setup.sh", "bash docs/autonomy/cloud-setup.sh",
                        "sh docs/autonomy/cloud-setup.sh", "bash -nv docs/autonomy/cloud-setup.sh"):
            proc = self.run_bash(command)
            self.assertEqual(proc.returncode, 0, f"{command}: {proc.stderr}")

    def test_script_that_writes_a_control_path(self) -> None:
        support.write(self.root, "bad.sh", CLOUD_SETUP + "echo 24 > .node-version\n")
        self.assertEqual(self.bash("bash bad.sh"), 2)
        self.assertEqual(self.bash("timeout 60 sh bad.sh"), 2)
        self.assertEqual(self.bash("bash -o pipefail bad.sh"), 2)
        self.assertEqual(self.bash("bash -n bad.sh"), 0)

    def test_dynamic_target_with_a_control_mention_fails_closed(self) -> None:
        support.write(self.root, "dyn.sh", 'f=.node-version\necho 24 > "$f"\n')
        self.assertEqual(self.bash("bash dyn.sh"), 2)
        support.write(self.root, "tmp.sh", 'out="$TMPDIR/x"\necho 24 > "$out"\n')
        self.assertEqual(self.bash("bash tmp.sh"), 0)
        support.write(self.root, "glob.sh", "cat .node-version\nrm -rf /tmp/node*\nsed -i 's/[a]/b/' notes.txt\n")
        self.assertEqual(self.bash("bash glob.sh"), 0)

    def test_dynamic_cd_resets_to_the_tree(self) -> None:
        support.write(self.root, "cd.sh", 'cd "$repo"\nrm AGENTS.md\n')
        self.assertEqual(self.bash("bash cd.sh"), 2)

    def test_nested_scripts_heredocs_and_comments(self) -> None:
        support.write(self.root, "outer.sh", "bash inner.sh\n")
        support.write(self.root, "inner.sh", "rm AGENTS.md\n")
        self.assertEqual(self.bash("bash outer.sh"), 2)
        support.write(self.root, "doc.sh", "python3 - <<'EOF'\nopen('AGENTS.md', 'w').write('x')\nEOF\n")
        self.assertEqual(self.bash("bash doc.sh"), 2)
        support.write(self.root, "notes.sh", "cat > notes.txt <<'EOF'\nsee AGENTS.md\nEOF\n")
        self.assertEqual(self.bash("bash notes.sh"), 0)
        support.write(self.root, "comment.sh", "# never run: rm AGENTS.md; rm Makefile\necho ok > /tmp/x # AGENTS.md\n")
        self.assertEqual(self.bash("bash comment.sh"), 0)

    def test_unparsable_script_keeps_the_text_heuristic(self) -> None:
        support.write(self.root, "broken.sh", "echo 'oops\nrm AGENTS.md\n")
        self.assertEqual(self.bash("bash broken.sh"), 2)

    def test_kernel_script_is_not_scanned(self) -> None:
        self.assertEqual(self.bash("python3 -I gates/gate.py check-repo"), 0)


class OpaqueScripts(HookTree):
    """Scripts that run a program the guard cannot name, source a script or run gh are checked like typed commands."""

    def test_dynamic_program_xargs_and_source_fail_closed(self) -> None:
        support.write(self.root, "x.sh", "CMD=rm\n$CMD AGENTS.md\n")
        support.write(self.root, "y.sh", "echo AGENTS.md | xargs rm\n")
        support.write(self.root, "z.sh", "rm AGENTS.md\n")
        for command in ("bash x.sh", "bash y.sh", "source z.sh", ". z.sh"):
            self.assertEqual(self.bash(command), 2, command)

    def test_gh_and_claude_rules_apply_inside_scripts(self) -> None:
        support.write(self.root, "gh.sh", "gh issue edit 5 --remove-label conductor:pause\n")
        support.write(self.root, "bare.sh", "claude -p --bare x\n")
        support.write(self.root, "gh.py", "import subprocess\nsubprocess.run(['gh', 'pr', 'merge', '12'])\n")
        for command in ("bash gh.sh", "bash bare.sh", "python3 gh.py"):
            proc = self.run_bash(command)
            self.assertEqual(proc.returncode, 2, f"{command}: {proc.stderr}")

    def test_reading_scripts_still_pass(self) -> None:
        support.write(self.root, "ok.sh", "gh pr view 12\necho x | xargs grep y\ncat AGENTS.md\n")
        self.assertEqual(self.bash("bash ok.sh"), 0)


class InterpreterScripts(HookTree):
    """Python and node scripts and heredocs keep the text heuristic with the proven-read exemption."""

    def test_reading_script_passes(self) -> None:
        support.write(self.root, "tool.py", "import json\n# reads gates/bash_rules.json\n"
                                            "print(json.load(open('gates/bash_rules.json')))\n"
                                            "open('out.json', 'w').write('{}')\n")
        self.assertEqual(self.bash("python3 tool.py"), 0)

    def test_reading_heredoc_with_a_comparison_passes(self) -> None:
        body = "import json\nd = json.load(open('gates/bash_rules.json'))\nprint(len(d) > 1, str(d).replace('a', 'b'))"
        self.assertEqual(self.bash("python3 - <<'EOF'\n" + body + "\nEOF"), 0)

    def test_writing_heredoc_and_script_stay_blocked(self) -> None:
        for body in ("import shutil\nshutil.copy('x', 'AGENTS.md')",
                     "p = 'gates/bash_rules.json'\nopen(p, 'w').write('{}')",
                     "f = open('AGENTS.md')\nimport os\nos.remove(f.name)",
                     "const fs = require('fs');\nfs.writeFileSync('AGENTS.md', 'x');"):
            prog = "node" if "require" in body else "python3"
            self.assertEqual(self.bash(f"{prog} - <<'EOF'\n{body}\nEOF"), 2, body)
            support.write(self.root, "tool.js" if prog == "node" else "tool.py", body + "\n")
            self.assertEqual(self.bash(f"{prog} tool.{'js' if prog == 'node' else 'py'}"), 2, body)


class Normaliser(unittest.TestCase):
    """Quoted punctuation is data, shell keywords and -xc are unwrapped, -n is a syntax check only."""

    def test_tokens_and_targets(self) -> None:
        self.assertEqual(cmdnorm.write_targets(cmdnorm.segments("grep -n '>' gates/lib/hooks.py")[0]), [])
        self.assertEqual(cmdnorm.write_targets(cmdnorm.segments("echo x > AGENTS.md")[0]), ["AGENTS.md"])
        self.assertEqual(cmdnorm.segments("eval echo x '>' AGENTS.md"), [["echo", "x", ">", "AGENTS.md"]])
        self.assertEqual(cmdnorm.segments("bash -c 'a && git push -f'"), [["a"], ["git", "push", "-f"]])
        self.assertEqual(cmdnorm.segments("bash -xc 'rm x'"), [["rm", "x"]])
        self.assertEqual(cmdnorm.segments("if true; then rm x; fi"), [["true"], ["rm", "x"]])
        self.assertIsNone(cmdnorm.segments("grep x 'oops"))

    def test_comments_only_in_scripts(self) -> None:
        self.assertEqual(cmdnorm.segments("# a; rm x", comments=True), [])
        self.assertEqual(cmdnorm.segments("echo '#' x # rm y", comments=True), [["echo", "#", "x"]])
        self.assertIn(["rm", "x"], cmdnorm.segments("# a; rm x"))
        self.assertEqual(cmdnorm.uncommented("a=1 # b\nc"), "a=1  ; c")

    def test_noexec(self) -> None:
        self.assertTrue(cmdnorm.noexec(["bash", "-n", "x.sh"]))
        self.assertTrue(cmdnorm.noexec(["zsh", "-nv", "x.sh"]))
        self.assertTrue(cmdnorm.noexec(["bash", "--norc", "-n", "x.sh"]))
        self.assertFalse(cmdnorm.noexec(["bash", "x.sh", "-n"]))
        self.assertFalse(cmdnorm.noexec(["bash", "-x", "x.sh"]))
        self.assertFalse(cmdnorm.noexec(["python3", "-n", "x.py"]))

    def test_inline_code_flags(self) -> None:
        self.assertEqual(cmdnorm.inline_code(["python3", "-Ic", "x"]), ["x"])
        self.assertEqual(cmdnorm.inline_code(["python3", "-W", "ignore", "-c", "x"]), ["x"])
        self.assertEqual(cmdnorm.inline_code(["python3", "tool.py", "-c", "x"]), [])
        self.assertEqual(cmdnorm.inline_code(["python3", "-m", "json.tool", "-c"]), [])
        self.assertEqual(cmdnorm.inline_code(["perl", "-ne", "x"]), ["x"])
        self.assertEqual(cmdnorm.inline_code(["node", "--eval=x"]), ["x"])
        self.assertEqual(cmdnorm.script_inputs(["python3", "-Ic", "x"]), [])
        self.assertEqual(cmdnorm.script_inputs(["bash", "-o", "pipefail", "+O", "extglob", "x.sh"]), ["x.sh"])

    def test_read_position(self) -> None:
        def pos(code: str, path: str) -> bool:
            start = code.index(path)
            return cmdnorm.read_position(code, start, start + len(path))

        self.assertTrue(pos("open('AGENTS.md')", "AGENTS.md"))
        self.assertTrue(pos("open('AGENTS.md', 'rb')", "AGENTS.md"))
        self.assertTrue(pos("Path('AGENTS.md').read_text()", "AGENTS.md"))
        self.assertTrue(pos("fs.readFileSync(`AGENTS.md`, 'utf8')", "AGENTS.md"))
        self.assertFalse(pos("open('AGENTS.md', 'w')", "AGENTS.md"))
        self.assertFalse(pos("os.open('AGENTS.md')", "AGENTS.md"))
        self.assertFalse(pos("open('AGENTS.md').name", "AGENTS.md"))
        self.assertFalse(pos("open(f'AGENTS.md')", "AGENTS.md"))
        self.assertFalse(pos("open('AGENTS.md' + x)", "AGENTS.md"))
        self.assertFalse(pos("Path('AGENTS.md').write_text('x')", "AGENTS.md"))


if __name__ == "__main__":
    unittest.main()
