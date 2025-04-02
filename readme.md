## PR Review Benchmark Tool

1. `clone_prs.py` -> To clone PR (yes! PR) into multiple similar PRs.
2. `export_gh_comments_to_csv.py` -> To export GitHub PR comments to CSV.
3. `eval_prs.py` -> To categorized inline PR reviews.

## Process
- Collect PRs from Open Source repos.
- Clone PRs into multiple multiple same PR using `clone_prs.py`.
- Install and Run Bots (manual).
- Export those comments using `export_gh_comments_to_csv.py`.
- Run `eval_prs.py` to categorize.
