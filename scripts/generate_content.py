#!/usr/bin/env python3
"""Generate Hugo content from Chef RecipeMD sources. Idempotent."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from recipemd import discover_recipes, load_recipe, build_jsonld  # noqa: E402

CONTENT = ROOT / "content"
GENERATED_MARKER = "generated_from_recipemd"


def version_sort_key(v: str):
    parts = re.split(r"[.-]", v)
    out = []
    for p in parts:
        out.append(int(p) if p.isdigit() else p)
    return out


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_body_md(recipe) -> str:
    lines: list[str] = []
    status = recipe.nutrition_status or "unknown"
    warnings = []
    if "estimated" in status.lower() or "pending" in status.lower():
        warnings.append(
            f"Nutrition numbers are still cooking — status is “{status}”, "
            "so we are not publishing a nutrition panel on this page yet. "
            "Ingredient grams below are for shopping and prep, not a finished weighed batch."
        )
    if not recipe.finished_mass():
        warnings.append(
            "Yield lists servings for now; finished edible mass unknown until a batch is weighed and the recipe is updated."
        )
    warnings.append(
        "Ingredient weights are as written on the card (proposed or card-aligned unless a CHANGELOG entry says they were weighed)."
    )
    lines.append('<div class="callout" role="note">')
    lines.append("<p><strong>Before you cook</strong></p>")
    lines.append("<ul>")
    for w in warnings:
        w_html = w.replace("**", "")
        lines.append(f"<li>{w_html}</li>")
    lines.append("</ul>")
    lines.append("</div>")
    lines.append("")
    if recipe.description:
        lines.append(recipe.description)
        lines.append("")
    if recipe.tags:
        chips = " ".join(f'<span class="tag-chip">{html_escape(tag)}</span>' for tag in recipe.tags)
        lines.append(f'<div class="tag-row">{chips}</div>')
        lines.append("")
    if recipe.yields:
        lines.append(f'<p class="yield-line"><strong>Yield:</strong> {html_escape(", ".join(recipe.yields))}</p>')
        lines.append("")
    lines.append("## Ingredients")
    lines.append("")
    for ing in recipe.ingredients:
        if ing.amount:
            lines.append(f"- **{ing.amount}** {ing.name}")
        else:
            lines.append(f"- {ing.name}")
    lines.append("")
    if recipe.instructions:
        lines.append("## Instructions")
        lines.append("")
        lines.append(recipe.instructions)
        lines.append("")
    lines.append("")
    lines.append('<p class="fine-print no-print">')
    lines.append(
        f"Recipe file: <code>recipes/{html_escape(recipe.recipe_id or 'UNKNOWN')}/v{html_escape(recipe.version)}.recipemd.md</code>. "
        "Tracking apps may be able to import this page by URL; we have not verified every importer."
    )
    lines.append("</p>")
    lines.append("")
    return "\n".join(lines)


def write_version_page(recipe, base_url: str) -> Path:
    slug = recipe.slug
    ver = recipe.version
    if not ver:
        raise ValueError(f"Missing version in {recipe.source_path}")
    dir_path = CONTENT / slug / f"v{ver}"
    dir_path.mkdir(parents=True, exist_ok=True)
    page_url = f"{base_url.rstrip('/')}/{slug}/v{ver}/"
    jsonld = build_jsonld(recipe, page_url)
    # Hugo front matter — Coder-generated, not Chef RecipeMD
    fm = {
        "title": recipe.title,
        "date": recipe.meta.get("date") or "2026-10-25",
        "draft": False,
        GENERATED_MARKER: True,
        "recipe_id": recipe.recipe_id,
        "recipe_version": ver,
        "slug_path": slug,
        "nutrition_status": recipe.nutrition_status,
        "tags": recipe.tags,
        "yields": recipe.yields,
        "jsonld_raw": json.dumps(jsonld, ensure_ascii=False),
        "canonical": page_url,
        "layout": "recipe",
        "type": "recipe",
        "is_version": True,
        "is_latest": False,
    }
    # Write YAML-ish front matter manually to avoid pyyaml dep; jsonld as JSON string
    body = render_body_md(recipe)
    # Use JSON front matter for reliable nesting
    header = json.dumps(fm, indent=2, ensure_ascii=False)
    text = f"+++\n{header}\n+++\n\n{body}"
    # Hugo TOML/YAML/JSON FM: JSON uses { } not +++
    text = f"{header}\n\n{body}"  # wait — Hugo JSON FM must be object only as first matter
    # Correct: Hugo accepts JSON front matter when file starts with {
    # But then body after closing }. Standard is:
    # {\n ... \n}\n\nbody
    out = dir_path / "index.md"
    out.write_text(f"{header}\n\n{body}", encoding="utf-8")
    return out


def write_latest_index(slug: str, recipes: list, base_url: str) -> Path:
    # recipes sorted newest last
    latest = recipes[-1]
    dir_path = CONTENT / slug
    dir_path.mkdir(parents=True, exist_ok=True)
    page_url = f"{base_url.rstrip('/')}/{slug}/"
    versions = [
        {
            "version": r.version,
            "path": f"/{slug}/v{r.version}/",
            "title": r.title,
            "date": r.meta.get("date", ""),
        }
        for r in recipes
    ]
    fm = {
        "title": latest.title,
        "date": latest.meta.get("date") or "2026-10-25",
        "draft": False,
        GENERATED_MARKER: True,
        "recipe_id": latest.recipe_id,
        "recipe_version": latest.version,
        "slug_path": slug,
        "nutrition_status": latest.nutrition_status,
        "tags": latest.tags,
        "yields": latest.yields,
        "jsonld_raw": json.dumps(build_jsonld(latest, page_url), ensure_ascii=False),
        "canonical": page_url,
        "layout": "recipe",
        "type": "recipe",
        "is_version": False,
        "is_latest": True,
        "latest_version": latest.version,
        "versions": versions,
        "cascade": {"type": "recipe"},
    }
    # Body: same as latest version + version list
    body = render_body_md(latest)
    body += "\n## Versions\n\n"
    body += (
        f'<p class="versions-list">This page is the <strong>current</strong> recipe '
        f'(<a href="/{slug}/">/{slug}/</a> → v{latest.version}). '
        "Older versions stay published so a past batch is still findable:</p>\n\n"
    )
    for v in versions:
        body += f"- [Version {v['version']}]({v['path']}) — locked once published\n"
    body += "\n"
    header = json.dumps(fm, indent=2, ensure_ascii=False)
    out = dir_path / "_index.md"
    out.write_text(f"{header}\n\n{body}", encoding="utf-8")
    return out


def clean_generated():
    if not CONTENT.exists():
        return
    for p in CONTENT.rglob("*.md"):
        if p.name == "_index.md" and p.parent == CONTENT:
            continue
        text = p.read_text(encoding="utf-8")
        if GENERATED_MARKER in text:
            p.unlink()
            # remove empty version dirs
            try:
                if p.parent != CONTENT and not any(p.parent.iterdir()):
                    p.parent.rmdir()
            except OSError:
                pass


def main():
    base_url = "https://rowdyeats.github.io/recipes"
    # Allow override from env/hugo — generator uses public Pages URL for canonical/jsonld
    import os

    base_url = os.environ.get("SITE_BASE_URL", base_url)
    clean_generated()
    CONTENT.mkdir(parents=True, exist_ok=True)
    home = CONTENT / "_index.md"
    if not home.exists():
        home.write_text(
            """---
title: RowdyEats Recipes
layout: home
---

Home-cooked recipes from the RowdyEats kitchen.
""",
            encoding="utf-8",
        )

    by_slug: dict[str, list] = {}
    for path in discover_recipes(ROOT):
        r = load_recipe(path)
        if not r.recipe_id or not r.version:
            raise SystemExit(f"Missing recipe_id/version metadata in {path}")
        by_slug.setdefault(r.slug, []).append(r)

    written = []
    for slug, rs in sorted(by_slug.items()):
        rs.sort(key=lambda r: version_sort_key(r.version))
        for r in rs:
            written.append(write_version_page(r, base_url))
        written.append(write_latest_index(slug, rs, base_url))

    print(f"Generated {len(written)} pages under content/ for baseURL={base_url}")


if __name__ == "__main__":
    main()
