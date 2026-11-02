"""Scheduled job: refresh the workshop / practice-group data and publish it to the target branch.

Target branch = first line of tools/sync-target.txt (set to each new round's branch,
switched to main once that branch is live).
Safety: does nothing unless the repo is on the target branch and nothing but the
data sources/outputs has changed.
"""
import datetime, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tools" / "auto-sync.log"
MINE = ["assets/data/workshops.json", "practice.html", "assets/תוכנית סדנאות"]


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


def git(*args, check=True):
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def main():
    target = (REPO / "tools" / "sync-target.txt").read_text(encoding="utf-8").splitlines()[0].strip()
    current = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if current != target:
        return log(f"skip: on '{current}', target is '{target}'")
    foreign = []
    for line in git("status", "--porcelain").stdout.splitlines():
        p = line[3:].strip().strip('"')
        if "~$" in p:
            continue
        if not any(p == m or p.startswith(m + "/") for m in MINE):
            foreign.append(p)
    if foreign:
        return log(f"skip: other uncommitted work present ({len(foreign)} paths)")
    subprocess.run([sys.executable, str(REPO / "tools" / "sync-workshops.py")],
                   cwd=REPO, capture_output=True, check=True)
    git("add", "--", *MINE)
    git("reset", "-q", "--", "assets/תוכנית סדנאות/~$*", check=False)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return log("no change")
    git("commit", "-q", "-m", "auto: refresh workshop and practice-group data from the docx/xlsx tables")
    git("push", "-q", "origin", target)
    log(f"committed and pushed to {target}")


try:
    main()
except Exception as e:
    log(f"ERROR: {e}")
    sys.exit(1)
