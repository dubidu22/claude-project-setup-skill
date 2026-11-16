# soundforge

Offline granular synthesis toolkit. Everything runs locally; the preview server binds to 127.0.0.1.

Layers (lowest first): core -> pipeline -> synth -> cli. Lower layers never import higher ones (enforced by import-linter in CI).

Golden render files live in tests/golden/ and are regenerated only by explicit decision.
