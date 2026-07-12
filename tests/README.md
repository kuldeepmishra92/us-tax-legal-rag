# Tests

One test file per phase: `test_phaseN_<topic>.py`. A phase is not considered done until its test file exists and passes.

Run everything:
```bash
pytest tests/ -v
```

Run a single phase:
```bash
pytest tests/test_phase1_parsing.py -v
```

## Conventions
- Tests read from real pipeline outputs (parsed chunks, live indexes, live API), not mocked fixtures — we're validating the actual artifact each phase produces, not a stand-in for it.
- Each phase's test file is written when that phase's code is written, not retrofitted afterward.
- A phase's Definition of Done (see [../docs/plan.md](../docs/plan.md)) always includes "this phase's tests pass" as a hard requirement before moving to the next phase.
- Before starting the next phase, run the *full* suite (`pytest tests/ -v`), not just the new file — catches regressions in earlier phases caused by later changes.
