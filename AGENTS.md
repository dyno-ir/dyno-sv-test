# Test Architecture Rules

- One ground truth per fact. Constants, categories, exclusions, source lists, top names, tech configs, output names, and build flags have one owner.
- Derive facts from the owning repo when possible. Do not duplicate a project's source list, test list, build config, or constants in the test harness.
- Keep one `infra.py`. Organize it by sections; do not split it into many small modules.
- Generic mechanisms first. Specialized projects use explicit hooks/overrides, not hardcoded branches or edge cases.
- Deep-integration projects own their specialized code in their own repo. The test adapter only invokes it.
- Generic targets use the shared C++ sim infra and keep their TB code in the test repo. Deep-integration targets keep their TB/cosim code in their own repo.
- One GL synth produces the GL netlist, checkpoint, and cell counts. One RTL elaboration produces the RTL sim design. Do not synthesize/elaborate the same design multiple times.
- Parameterize tech. Liberty, flipflops, memories, flow symbols, checkpoints, and output names follow the selected tech; no hardcoded tech.
- No layout coupling. Dyno must run independently of any dashboard/consumer repo. Use explicit `DYNO_ROOT`, `DYNO_BUILD`, and `DYNO_WORK`; test work lives inside dyno.
- No duplicate builds/checkouts. One dependency checkout and one build/test runner per project.
- Reliable pass/fail. Use an explicit result protocol. Pass only when the program halts with a valid OK result. Fail on ERROR, bus failure, halt without result, missing summary, empty program/test set, partial correctness tests, or mismatches.
- Partial results are allowed only for benchmark programs, never for correctness tests.
- Empty test/program sets must fail, not pass.
- Missing required submodules/repos must fail when tests are expected, not silently skip.
- Remove unused/stale code, variables, exclusions, and files.
