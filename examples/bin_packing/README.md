# Online Bin Packing Benchmark

This benchmark evolves a single online bin-packing heuristic.

- Baseline: first-fit placement.
- Common improvement: best-fit placement, choosing the bin with the least remaining capacity after insertion.
- Evaluator: fixed item streams, hard correctness, lower `bins_used` is better.

Run with a local known-improving patch:

```bash
python3 -m aevolve_runtime.cli run \
  --task examples/bin_packing/task.yaml \
  --patch-dir examples/bin_packing/patches \
  --run-id bin-packing-known
```

Run with live API generation after setting the configured API key environment variable:

```bash
python3 -m aevolve_runtime.cli run \
  --task examples/bin_packing/task.yaml \
  --generate 6 \
  --run-id bin-packing-live
```
