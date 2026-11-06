# RowdyEats Recipes

Public static recipe site for **Cronometer Gold** URL import (import itself **not verified** here).

- **Chef source of truth:** `recipes/<ID>/vX.Y.recipemd.md` (RecipeMD 2.4.0) + `CHANGELOG.md`
- **Coder:** Hugo site + `scripts/generate_content.py` (RecipeMD → pages + schema.org JSON-LD)
- **Pages:** `https://rowdyeats.github.io/recipes/`

## Local build

```bash
python3 scripts/generate_content.py
python3 -m unittest discover -s tests -v
hugo build --minify --baseURL https://rowdyeats.github.io/recipes/
```

## Versioning

- Immutable: `/gcs-cc/v1.0/`
- Stable latest: `/gcs-cc/` (points at current version content)
- Never overwrite a published version file; bump `vX.Y` and CHANGELOG.

## Nutrition policy

JSON-LD `nutrition` is omitted unless metadata marks `weighed-batch` and supplies per-serving totals. `carbohydrateContent` is **total carbs**, never net carbs.
