# 17-Input Sorting Network Benchmark

This benchmark tests whether candidate generation can improve the best-known size for a 17-input sorting network.

The seed network uses 71 compare-exchange elements across 12 layers, matching the public best-known upper bound listed by Bert Dobbelaere. The evaluator verifies every binary input by the 0/1 principle and minimizes comparator count.

Run a live search:

```bash
DEEPSEEK_API_KEY=... python3 -m aevolve_runtime.cli run \
  --task examples/sorting_network17/task.yaml \
  --generate 24 \
  --run-id sorting17-live
```

Any valid candidate with `size < 71` would be a serious result and should be independently verified before making any public claim.
