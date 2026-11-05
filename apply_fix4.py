"""classify_pdfs / audit_results: stop hardcoding editions 75 and 77."""
import shutil, sys
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
BACKUP = ROOT / ".backup_fixes" / datetime.now().strftime("%Y%m%d_%H%M%S_fix4")


def patch(rel, edits):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"{rel} not found. Run from the folder containing manage.py.")
    s = p.read_text(encoding="utf-8")
    for old, new in edits:
        if new in s:
            print(f"[SKIP] {rel}: already patched")
            return
        if old not in s:
            sys.exit(f"[FAIL] {rel}: expected text not found:\n{old}")
        s = s.replace(old, new, 1)
    compile(s, rel, "exec")
    dest = BACKUP / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    p.write_text(s, encoding="utf-8")
    print(f"[OK] {rel} patched")


patch("results/management/commands/classify_pdfs.py", [
    ("    def handle(self, *args, **options):\n",
     "    def add_arguments(self, parser):\n"
     "        parser.add_argument('--edition', type=int, nargs='*',\n"
     "                            help='Edition numbers to classify (default: 75 77)')\n"
     "        parser.add_argument('--all', action='store_true',\n"
     "                            help='Classify every championship with a cached PDF')\n\n"
     "    def handle(self, *args, **options):\n"),
    ("        championships = Championship.objects.filter(edition__in=[75, 77])\n",
     "        if options.get('all'):\n"
     "            championships = Championship.objects.all().order_by('edition')\n"
     "        else:\n"
     "            championships = Championship.objects.filter(\n"
     "                edition__in=options.get('edition') or [75, 77]).order_by('edition')\n"),
])

patch("results/management/commands/audit_results.py", [
    ("for champ in Championship.objects.filter(edition__in=[75, 77]):",
     "for champ in Championship.objects.filter(communiques__isnull=False).distinct().order_by('edition'):"),
])
print(f"Backups in {BACKUP}")
