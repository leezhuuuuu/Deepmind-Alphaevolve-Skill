# Golomb Ruler Benchmark

This benchmark evolves a construction for an order-9 Golomb ruler.

A Golomb ruler is a strictly increasing list of marks where every pairwise distance is unique.
The evaluator checks validity and minimizes the total ruler length.

Run a live model search:

```bash
DEEPSEEK_API_KEY=... python3 -m aevolve_runtime.cli run \
  --task examples/golomb_ruler/task.yaml \
  --generate 8 \
  --run-id golomb-live
```

The baseline is intentionally valid but long, so useful candidate generations should sharply reduce `length`.
