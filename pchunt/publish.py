"""Publish the website to GitHub Pages: export site/ (pchunt.export_site) and force-push it as the only commit of the
gh-pages branch of this folder's `origin`, so the repository does not grow with every day's price files.

    python -X utf8 -m pchunt.publish            # export + push
    python -X utf8 -m pchunt.publish --no-export
"""
import shutil
import subprocess
import sys
from datetime import datetime

from .db import DATA, ROOT
from .export_site import export

SITE = ROOT / "site"
GIT = DATA / "pages.git"


def git(*args, cwd=None):
    p = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args[:4])}: {p.stderr.strip()}")
    return p.stdout.strip()


def publish(do_export=True):
    if do_export:
        info = export(SITE)
        print(f"exported: {info['in_stock']} in stock, {info['sold_out']} sold out", flush=True)
    remote = git("remote", "get-url", "origin")
    if GIT.exists():
        shutil.rmtree(GIT, ignore_errors=True)
    tree = ["--git-dir", str(GIT), "--work-tree", str(SITE)]
    git("--git-dir", str(GIT), "init", "-q", "-b", "gh-pages")
    git(*tree, "add", "-A")
    git(*tree, "commit", "-q", "-m", f"Prices {datetime.now():%Y-%m-%d %H:%M}")
    git(*tree, "push", "-q", "--force", remote, "gh-pages")
    print(f"pushed site/ to {remote} gh-pages", flush=True)


if __name__ == "__main__":
    publish("--no-export" not in sys.argv)
