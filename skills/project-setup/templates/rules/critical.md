---
paths:
{{critical_yaml}}
---

# Critical paths

You are working on a file that makes a PR **critical**. For this PR:

- Label it `critical` and say in the PR body what could break.
- Post a plan on the issue before any code{{#unless autonomous}} and wait for the owner's approval{{/unless}}.
- Review may take up to {{critical_review_rounds}} rounds. Must-fix findings after the last round stop the PR for the owner.
{{#if supervised}}
- The owner merges.
{{/if}}
{{#if guided}}
- The owner merges. The lead does not, even with a passing review.
{{/if}}
{{#if autonomous}}
- The lead may merge after a passing review and green CI.
{{/if}}
- Keep it small: a critical change does not share a PR with unrelated work.

<!-- {{mark}} -->
