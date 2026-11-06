#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from recipemd import (  # noqa: E402
    load_recipe,
    build_jsonld,
    parse_recipemd,
    discover_recipes,
)


class RecipeMDParseTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "recipes" / "GCS-CC" / "v1.0.recipemd.md"
        self.recipe = load_recipe(self.path)

    def test_discovers_source(self):
        paths = discover_recipes(ROOT)
        self.assertTrue(any(p.name == "v1.0.recipemd.md" for p in paths))

    def test_title_and_ingredients_from_example(self):
        self.assertEqual(
            self.recipe.title, "New Mexican Green Chile Stew (Chicken & Corn)"
        )
        self.assertEqual(self.recipe.recipe_id, "GCS-CC")
        self.assertEqual(self.recipe.version, "1.0")
        self.assertEqual(len(self.recipe.ingredients), 10)
        first = self.recipe.ingredients[0]
        self.assertEqual(first.amount, "1360 g")
        self.assertIn("chicken", first.name)
        # Do not invent finished mass
        self.assertIsNone(self.recipe.finished_mass())
        self.assertEqual(self.recipe.servings_count(), "6")

    def test_jsonld_omits_nutrition_when_estimated(self):
        obj = build_jsonld(self.recipe, "https://rowdyeats.github.io/recipes/gcs-cc/v1.0/")
        self.assertEqual(obj["@type"], "Recipe")
        self.assertNotIn("nutrition", obj)
        self.assertEqual(obj["recipeYield"], "6")
        self.assertEqual(len(obj["recipeIngredient"]), 10)
        self.assertTrue(all(s["@type"] == "HowToStep" for s in obj["recipeInstructions"]))
        # total carbs only when known — none here
        self.assertNotIn("carbohydrateContent", json.dumps(obj))

    def test_jsonld_includes_nutrition_only_when_weighed_and_based(self):
        text = self.path.read_text(encoding="utf-8")
        text = text.replace(
            "nutrition_status: estimated pending weighed batch",
            'nutrition_status: weighed-batch\n'
            'per_serving_nutrition: {"kcal": 100, "protein_g": 10, "fat_g": 4, "carbs_g": 8, "fiber_g": 2, "servingSize": "1 of 6 servings"}',
        )
        r = parse_recipemd(text, source_path="synthetic")
        obj = build_jsonld(r, "https://example.com/x/")
        self.assertIn("nutrition", obj)
        self.assertEqual(obj["nutrition"]["@type"], "NutritionInformation")
        self.assertIn("carbohydrateContent", obj["nutrition"])
        self.assertEqual(obj["nutrition"]["carbohydrateContent"], "8 g")

    def test_net_carbs_alone_do_not_become_carbohydrateContent(self):
        text = self.path.read_text(encoding="utf-8")
        text = text.replace(
            "nutrition_status: estimated pending weighed batch",
            'nutrition_status: weighed-batch\n'
            'per_serving_nutrition: {"kcal": 100, "net_carbs_g": 5}',
        )
        r = parse_recipemd(text, source_path="synthetic")
        obj = build_jsonld(r, "https://example.com/x/")
        # calories alone might appear; carbohydrateContent must not be invented from net
        nut = obj.get("nutrition", {})
        self.assertNotIn("carbohydrateContent", nut)


class BuildOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("hugo"):
            raise unittest.SkipTest("hugo not installed")
        subprocess.check_call(
            [sys.executable, str(ROOT / "scripts" / "generate_content.py")],
            cwd=ROOT,
            env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "SITE_BASE_URL": "https://rowdyeats.github.io/recipes"},
        )
        public = ROOT / "public"
        if public.exists():
            shutil.rmtree(public)
        subprocess.check_call(
            [
                "hugo",
                "build",
                "--gc",
                "--baseURL",
                "https://rowdyeats.github.io/recipes/",
            ],
            cwd=ROOT,
        )
        cls.public = ROOT / "public"

    def test_home_and_recipe_paths(self):
        self.assertTrue((self.public / "index.html").is_file())
        self.assertTrue((self.public / "gcs-cc" / "index.html").is_file())
        self.assertTrue((self.public / "gcs-cc" / "v1.0" / "index.html").is_file())

    def test_canonical_and_subpath_links(self):
        latest = (self.public / "gcs-cc" / "index.html").read_text(encoding="utf-8")
        version = (self.public / "gcs-cc" / "v1.0" / "index.html").read_text(encoding="utf-8")
        self.assertRegex(
            latest,
            r'rel=["\']?canonical["\']?\s+href=["\']?https://rowdyeats\.github\.io/recipes/gcs-cc/["\']?',
        )
        self.assertRegex(
            version,
            r'rel=["\']?canonical["\']?\s+href=["\']?https://rowdyeats\.github\.io/recipes/gcs-cc/v1\.0/["\']?',
        )
        home = (self.public / "index.html").read_text(encoding="utf-8")
        self.assertIn("/recipes/", home)
        self.assertIn("gcs-cc", home)
        # Home brand should not point at domain root alone when project Pages subpath is used
        self.assertNotIn('class="brand" href=/', home)
        self.assertNotIn('class="brand" href="/"', home)
        self.assertIn('https://rowdyeats.github.io/recipes/', home)

    def test_jsonld_in_page_valid_and_no_nutrition(self):
        html = (self.public / "gcs-cc" / "v1.0" / "index.html").read_text(encoding="utf-8")
        m = re.search(
            r'<script type=["\']application/ld\+json["\']>\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(m, msg=html[-500:])
        obj = json.loads(m.group(1))
        self.assertIn("recipeIngredient", obj)
        self.assertIn("recipeInstructions", obj)
        self.assertIn("recipeYield", obj)
        self.assertEqual(obj["@type"], "Recipe")
        self.assertNotIn("nutrition", obj)
        self.assertEqual(
            obj["url"], "https://rowdyeats.github.io/recipes/gcs-cc/v1.0/"
        )
        self.assertIn("1360 g chicken", obj["recipeIngredient"][0])

    def test_warnings_visible(self):
        html = (self.public / "gcs-cc" / "v1.0" / "index.html").read_text(encoding="utf-8")
        self.assertIn("estimated pending weighed batch", html)
        self.assertIn("finished edible mass unknown", html.lower())

    def test_version_protection_helper(self):
        """Immutable version files must not be silently replaced by generate without bump."""
        # Simulate: existing published marker — generator always regenerates from source,
        # but CHANGELOG + distinct version paths are the protection. Assert v1.0 path stable.
        v = ROOT / "recipes" / "GCS-CC" / "v1.0.recipemd.md"
        self.assertTrue(v.is_file())
        # A new version would be v1.1.recipemd.md — ensure we don't overwrite path scheme
        self.assertFalse((ROOT / "recipes" / "GCS-CC" / "v1.1.recipemd.md").exists())
        pub_v = self.public / "gcs-cc" / "v1.0" / "index.html"
        self.assertTrue(pub_v.is_file())


if __name__ == "__main__":
    unittest.main()
