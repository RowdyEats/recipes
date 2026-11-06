#!/usr/bin/env python3
"""RecipeMD 2.4.0 subset parser + JSON-LD helpers for RowdyEats recipes site.

Does not invent nutrition. HTML comment metadata is optional sidecar.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
# RecipeMD amounts: leading emphasis then name
INGREDIENT_RE = re.compile(
    r"^-\s+(?:\*(?P<amount>[^*]+)\*\s+)?(?P<name>.+?)\s*$"
)
TAG_PARA_RE = re.compile(r"^\*(?P<tags>.+)\*$")
YIELD_PARA_RE = re.compile(r"^\*\*(?P<yields>.+)\*\*$")


@dataclass
class Ingredient:
    name: str
    amount: Optional[str] = None

    def as_text(self) -> str:
        if self.amount:
            return f"{self.amount.strip()} {self.name.strip()}"
        return self.name.strip()


@dataclass
class Recipe:
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    yields: list[str] = field(default_factory=list)
    ingredients: list[Ingredient] = field(default_factory=list)
    instructions: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    source_path: str = ""

    @property
    def recipe_id(self) -> str:
        return self.meta.get("recipe_id") or ""

    @property
    def version(self) -> str:
        return self.meta.get("version") or ""

    @property
    def nutrition_status(self) -> str:
        return self.meta.get("nutrition_status") or ""

    @property
    def slug(self) -> str:
        rid = self.recipe_id or Path(self.source_path).parent.name
        return rid.lower().replace("_", "-")

    def servings_count(self) -> Optional[str]:
        for y in self.yields:
            m = re.search(r"(\d+)\s*servings?", y, re.I)
            if m:
                return m.group(1)
        return None

    def finished_mass(self) -> Optional[str]:
        for y in self.yields:
            m = re.search(r"(\d+(?:\.\d+)?)\s*g\b", y, re.I)
            if m:
                return f"{m.group(1)} g"
        return None


def parse_html_comment_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for block in HTML_COMMENT_RE.findall(text):
        for line in block.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key:
                meta[key] = val
    return meta


def strip_html_comments(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text)


def parse_recipemd(text: str, source_path: str = "") -> Recipe:
    meta = parse_html_comment_meta(text)
    body = strip_html_comments(text).strip()
    lines = body.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"{source_path or '<stdin>'}: RecipeMD requires H1 title")
    title = lines[0][2:].strip()

    # Split on thematic breaks ---
    parts: list[list[str]] = [[]]
    for line in lines[1:]:
        if re.fullmatch(r"-{3,}", line.strip()):
            parts.append([])
        else:
            parts[-1].append(line)

    preamble = parts[0] if parts else []
    ingredient_lines = parts[1] if len(parts) > 1 else []
    instruction_lines = parts[2] if len(parts) > 2 else []
    # If only one break, remaining after ingredients may be empty; if no second
    # break but instructions follow ingredients lists, RecipeMD allows omitting
    # second --- when no instructions. We already split correctly.

    tags: list[str] = []
    yields: list[str] = []
    desc_lines: list[str] = []
    for line in preamble:
        s = line.strip()
        if not s:
            if desc_lines and desc_lines[-1] != "":
                desc_lines.append("")
            continue
        tm = TAG_PARA_RE.fullmatch(s)
        ym = YIELD_PARA_RE.fullmatch(s)
        if tm and not tags:
            tags = [t.strip() for t in _comma_split(tm.group("tags"))]
            continue
        if ym and not yields:
            yields = [y.strip() for y in _comma_split(ym.group("yields"))]
            continue
        desc_lines.append(line)
    description = "\n".join(desc_lines).strip()

    ingredients: list[Ingredient] = []
    for line in ingredient_lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            # ingredient group heading — keep as name-only marker for display
            ingredients.append(Ingredient(name=s.lstrip("#").strip(), amount=None))
            continue
        m = INGREDIENT_RE.match(s)
        if not m:
            continue
        ingredients.append(
            Ingredient(name=m.group("name").strip(), amount=(m.group("amount") or None))
        )

    instructions = "\n".join(instruction_lines).strip()
    return Recipe(
        title=title,
        description=description,
        tags=tags,
        yields=yields,
        ingredients=ingredients,
        instructions=instructions,
        meta=meta,
        source_path=source_path,
    )


def _comma_split(s: str) -> list[str]:
    # RecipeMD: comma not a divider if both neighbors are digits
    out: list[str] = []
    buf: list[str] = []
    for i, ch in enumerate(s):
        if ch == "," and not (
            i > 0 and i + 1 < len(s) and s[i - 1].isdigit() and s[i + 1].isdigit()
        ):
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def parse_nutrition_from_meta(meta: dict[str, str]) -> Optional[dict[str, Any]]:
    """Only emit schema nutrition when status is weighed-batch AND per_100g/serving known.

    Chef example is 'estimated pending weighed batch' → omit entirely.
    """
    status = (meta.get("nutrition_status") or "").lower()
    if "weighed-batch" not in status.replace(" ", "-") and "weighed batch" not in status:
        # Accept explicit weighed-batch token only
        if "weighed-batch" not in status.replace(" ", ""):
            if not status.startswith("weighed"):
                return None
    # Prefer structured per_serving JSON in meta if present
    raw = meta.get("per_serving_nutrition") or meta.get("nutrition_json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def build_jsonld(recipe: Recipe, page_url: str) -> dict[str, Any]:
    yields: list[Any] = []
    servings = recipe.servings_count()
    if servings:
        yields.append(servings)
    for y in recipe.yields:
        # Prefer numeric servings already added; keep non-serving yield tokens (e.g. mass)
        if re.search(r"servings?", y, re.I):
            continue
        if y not in yields:
            yields.append(y)

    obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": recipe.title,
        "url": page_url,
    }
    if recipe.description:
        obj["description"] = recipe.description
    if recipe.tags:
        obj["keywords"] = ", ".join(recipe.tags)
    if yields:
        obj["recipeYield"] = yields if len(yields) > 1 else yields[0]
    if recipe.ingredients:
        obj["recipeIngredient"] = [i.as_text() for i in recipe.ingredients if not i.name.startswith("")]
        # filter group headings that we stored without amount and look like headings — already plain
        obj["recipeIngredient"] = [i.as_text() for i in recipe.ingredients]
    if recipe.instructions:
        steps = []
        for line in recipe.instructions.splitlines():
            s = line.strip()
            if not s:
                continue
            s = re.sub(r"^\d+\.\s*", "", s)
            steps.append({"@type": "HowToStep", "text": s})
        if steps:
            obj["recipeInstructions"] = steps
    if recipe.version:
        obj["version"] = recipe.version
    if recipe.meta.get("date"):
        obj["datePublished"] = recipe.meta["date"]

    nutrition = parse_nutrition_from_meta(recipe.meta)
    if nutrition and servings:
        ni: dict[str, Any] = {"@type": "NutritionInformation"}
        # Map only known total-carb aware fields; never put net carbs in carbohydrateContent
        mapping = {
            "calories": "calories",
            "kcal": "calories",
            "protein_g": "proteinContent",
            "proteinContent": "proteinContent",
            "fat_g": "fatContent",
            "fatContent": "fatContent",
            "carbs_g": "carbohydrateContent",
            "carbohydrateContent": "carbohydrateContent",
            "fiber_g": "fiberContent",
            "fiberContent": "fiberContent",
            "sodium_mg": "sodiumContent",
            "sodiumContent": "sodiumContent",
            "servingSize": "servingSize",
        }
        for k, sk in mapping.items():
            if k in nutrition and nutrition[k] is not None:
                val = nutrition[k]
                if sk == "calories" and isinstance(val, (int, float)):
                    ni[sk] = f"{val} kcal"
                elif sk.endswith("Content") and isinstance(val, (int, float)):
                    unit = "mg" if "sodium" in sk.lower() else "g"
                    ni[sk] = f"{val} {unit}"
                else:
                    ni[sk] = val
        # Refuse nutrition without carbohydrateContent being total carbs if net_carbs only provided
        if "net_carbs_g" in nutrition and "carbs_g" not in nutrition and "carbohydrateContent" not in ni:
            # cannot emit carbs from net alone
            pass
        if len(ni) > 1:
            obj["nutrition"] = ni
    return obj


def discover_recipes(root: Path) -> list[Path]:
    return sorted(root.glob("recipes/*/v*.recipemd.md"))


def load_recipe(path: Path) -> Recipe:
    return parse_recipemd(path.read_text(encoding="utf-8"), source_path=str(path))


def recipe_to_dict(recipe: Recipe) -> dict[str, Any]:
    d = asdict(recipe)
    return d


if __name__ == "__main__":
    import sys

    p = Path(sys.argv[1])
    r = load_recipe(p)
    print(json.dumps(build_jsonld(r, "https://example.com/gcs-cc/v1.0/"), indent=2))
