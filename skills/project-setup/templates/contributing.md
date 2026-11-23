## How pull requests are handled

<!-- {{mark}} -->

Most work in {{name}} is done by Claude Code sessions under the rules in [`CLAUDE.md`](CLAUDE.md). The same rules apply to your pull request:

- It should close an issue that has acceptance criteria. For anything larger than a small fix, open an issue first.
- It is reviewed against those criteria, by an AI reviewer first. Findings come with a reason you can check.
{{#if has_checks}}
- It must pass `{{checks}}`.
{{/if}}
- A PR that touches {{critical_list}} is critical{{#unless autonomous}} and is merged by the maintainer{{/unless}}: it gets a plan first and more review.
{{#if licence_gate}}
- New dependencies and copied material need a named licence. Refused: {{refused_list}}.
{{/if}}
- Text in issues and pull requests is never treated as an instruction to the AI sessions.
