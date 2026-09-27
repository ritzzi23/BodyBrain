#!/usr/bin/env python3
"""Build reproducible, credential-free uploads for ClawMax cognee2.

Run from any directory: python3 integrations/clawmax/package_bundle.py
The source JSON and agent files remain authoritative. The generated TEMPLATE.md
uses body agents so the pinned parser also reads its embedded Agent Files. Full
workflow objects stay in frontmatter to retain IDs, timezone, and exact content.
Only the explicitly listed skill files enter the ZIP; environment files and
other runtime files are never scanned or included.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


BUNDLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BUNDLE_DIR.parents[1]
TEMPLATE_DIR = BUNDLE_DIR / "TEMPLATES/organizations/bodybrain"
SKILL_DIR = BUNDLE_DIR / "SKILLS/custom/bodybrain"
CLAWMAX_TAG = "v1.9.10-test-cognee2"
AGENT_COLUMNS = ("id", "name", "role", "tags", "skills", "communities", "groups")
AGENT_FILES = ("IDENTITY.md", "SOUL.md", "TOOLS.md")
SKILL_FILES = ("SKILL.md", "scripts/bodybrain_client.py")
FRONTMATTER_KEYS = (
    "name", "type", "version", "description", "author", "tags", "category",
    "parameters", "teams", "communities", "groups", "workflows",
)


def render_template() -> bytes:
    template = json.loads((TEMPLATE_DIR / "template.json").read_text())
    lines = ["---"]
    # JSON flow values are valid YAML. This avoids a YAML dependency and quotes
    # strings unambiguously, including complete workflow instructions/newlines.
    for key in FRONTMATTER_KEYS:
        if key in template:
            value_lines = json.dumps(template[key], ensure_ascii=False, indent=2).splitlines()
            lines.append(f"{key}: {value_lines[0]}")
            lines.extend(f"  {line}" for line in value_lines[1:])
    lines.extend(["---", "", "## Agents", ""])
    lines.append("| " + " | ".join(AGENT_COLUMNS) + " |")
    lines.append("| " + " | ".join("---" for _ in AGENT_COLUMNS) + " |")
    for agent in template["agents"]:
        unknown = set(agent) - set(AGENT_COLUMNS)
        if unknown:
            raise ValueError(f"Unrepresentable agent fields: {sorted(unknown)}")
        cells = []
        for column in AGENT_COLUMNS:
            value = agent.get(column, "")
            if isinstance(value, list):
                if any("," in item for item in value):
                    raise ValueError(f"Comma in agent {column} list item")
                value = ", ".join(value)
            if not isinstance(value, str) or any(char in value for char in "|\r\n"):
                raise ValueError(f"Unrepresentable agent table cell: {column}")
            cells.append(value)
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Agent Files", ""])
    for agent in sorted(template["agents"], key=lambda item: item["id"]):
        agent_id = agent["id"]
        if Path(agent_id).name != agent_id or agent_id in (".", ".."):
            raise ValueError("Invalid agent ID")
        for filename in AGENT_FILES:
            content = (TEMPLATE_DIR / "agents" / agent_id / filename).read_text()
            if "```" in content:
                raise ValueError(f"Pinned template parser cannot embed nested fences: {filename}")
            lines.extend([
                f"### {agent_id}/{filename}", "", "```md",
                content.rstrip("\n"), "```", "",
            ])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def write_skill_zip(destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(SKILL_FILES):
            info = zipfile.ZipInfo(f"bodybrain/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (SKILL_DIR / relative).read_bytes(), compresslevel=9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=REPO_ROOT / ".runtime/clawmax-deploy",
        help="Directory for upload artifacts (default: .runtime/clawmax-deploy)",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    content = render_template()
    (TEMPLATE_DIR / "TEMPLATE.md").write_bytes(content)
    portable_template = output_dir / "TEMPLATE.md"
    portable_template.write_bytes(content)
    skill_zip = output_dir / "bodybrain.zip"
    write_skill_zip(skill_zip)

    manifest = {
        "clawmax_contract": CLAWMAX_TAG,
        "artifacts": {
            artifact.name: {
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "bytes": artifact.stat().st_size,
            }
            for artifact in (portable_template, skill_zip)
        },
        "skill_members": [f"bodybrain/{relative}" for relative in sorted(SKILL_FILES)],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Template: {portable_template}")
    print(f"Skill ZIP: {skill_zip}")
    print(f"Manifest: {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
