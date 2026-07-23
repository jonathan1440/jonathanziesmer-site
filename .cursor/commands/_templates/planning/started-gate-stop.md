## /gh-update-plan stopped — implementation in progress

Cannot refresh the plan while branches have non-merge implementation commits.

| Branch | Repo | Non-merge commits ahead of base |
|--------|------|----------------------------------|
{started_rows}

**What to do:** Finish or land in-flight work, merge/rebase manually, or run `/gh-plan` directly if you intentionally want a fresh breakdown. Re-run `/gh-update-plan` when spec, story, and task branches have no non-merge commits ahead of their bases (merge-only history from sync is OK).
