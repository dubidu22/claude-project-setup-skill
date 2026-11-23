---
paths:
{{manifests_yaml}}
---

# Licence gate

You are changing a dependency list. For every dependency, copied file, model, font or sample text a PR adds:

1. Find the licence at the source (the repository's licence file, the package metadata) and quote its SPDX identifier in the PR body.
2. Refused: {{refused_list}}.
3. Copied code keeps its copyright and licence notice at the top of the file.
4. Record it where the project lists third-party material (for example `THIRD_PARTY_LICENSES.md`), in the same PR.
5. When unsure, stop, label the PR `critical` and ask the owner.

<!-- {{mark}} -->
