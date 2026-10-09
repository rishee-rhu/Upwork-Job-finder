"""Builds artifact/findjobs.html: UI shell + pipeline logic + example profiles."""
import json
from pathlib import Path

here = Path(__file__).parent
root = here.parent
shell = (here / "findjobs.shell.html").read_text()
logic = (here / "pipeline.js").read_text()
examples = {"Pooja Ganechari": json.loads((root / "examples/profile.pooja.json").read_text()),
            "Somya Kumar": json.loads((root / "examples/profile.somya.json").read_text())}
out = shell.replace("/*LOGIC*/", logic).replace("/*EXAMPLES*/{}", json.dumps(examples))
(here / "findjobs.html").write_text(out)
print(f"wrote findjobs.html ({len(out):,} bytes)")
