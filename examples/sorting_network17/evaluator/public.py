"""Evaluator for 17-input sorting networks."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import time


INPUTS = 17
TOTAL_BINARY_INPUTS = 1 << INPUTS
INVALID_SIZE = 10_000
KNOWN_BEST_SIZE = 71


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        module = _load_candidate(Path(args.candidate))
        network = module.construct_network()
        analysis = _analyze_network(network)
        valid = analysis["valid"]
        size = analysis["size"] if valid else INVALID_SIZE
        depth = analysis["depth"] if valid else INVALID_SIZE
        metrics = {
            "correctness": 1.0 if valid else 0.0,
            "size": float(size),
            "depth": float(depth),
            "breaks_known_best": 1.0 if valid and size < KNOWN_BEST_SIZE else 0.0,
            "failed_inputs": float(analysis["failed_inputs"]),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        feedback = {
            "size": analysis["size"],
            "depth": analysis["depth"],
            "layer_sizes": analysis["layer_sizes"],
            "failed_inputs": analysis["failed_inputs"],
            "counterexamples": analysis["counterexamples"],
            "errors": analysis["errors"],
        }
        print(json.dumps({"valid": valid, "metrics": metrics, "feedback": feedback}, sort_keys=True))
        return 0
    except Exception as exc:
        metrics = {
            "correctness": 0.0,
            "size": float(INVALID_SIZE),
            "depth": float(INVALID_SIZE),
            "breaks_known_best": 0.0,
            "failed_inputs": float(TOTAL_BINARY_INPUTS),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        print(json.dumps({"valid": False, "metrics": metrics, "feedback": {"errors": [str(exc)]}}))
        return 0


def _load_candidate(candidate_dir: Path):
    path = candidate_dir / "examples" / "sorting_network17" / "src" / "network.py"
    spec = importlib.util.spec_from_file_location("candidate_network17", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "construct_network"):
        raise RuntimeError("candidate module has no construct_network")
    return module


def _analyze_network(network) -> dict:
    errors: list[str] = []
    layers, normalized_errors = _normalize_network(network)
    errors.extend(normalized_errors)
    layer_sizes = [len(layer) for layer in layers]
    comparators = [pair for layer in layers for pair in layer]
    if errors:
        return _result(False, layers, layer_sizes, len(comparators), len(layers), TOTAL_BINARY_INPUTS, [], errors)

    counterexamples: list[str] = []
    failed_inputs = 0
    sorted_masks = _sorted_masks()
    for mask in range(TOTAL_BINARY_INPUTS):
        output = _apply_network(mask, comparators)
        if output not in sorted_masks:
            failed_inputs += 1
            if len(counterexamples) < 8:
                counterexamples.append(_bits(mask))
    valid = failed_inputs == 0
    if not valid:
        errors.append("network failed to sort all binary inputs")
    return _result(valid, layers, layer_sizes, len(comparators), len(layers), failed_inputs, counterexamples, errors)


def _normalize_network(network) -> tuple[list[list[tuple[int, int]]], list[str]]:
    errors: list[str] = []
    if not isinstance(network, (list, tuple)):
        return [], ["construct_network must return a list"]
    if not network:
        return [], ["network must not be empty"]

    if all(_looks_like_pair(item) for item in network):
        raw_layers = [network]
    else:
        raw_layers = network

    layers: list[list[tuple[int, int]]] = []
    for layer_index, raw_layer in enumerate(raw_layers):
        if not isinstance(raw_layer, (list, tuple)):
            errors.append(f"layer {layer_index} must be a list")
            continue
        used: set[int] = set()
        layer: list[tuple[int, int]] = []
        for item in raw_layer:
            if not _looks_like_pair(item):
                errors.append(f"invalid comparator in layer {layer_index}: {item!r}")
                continue
            left, right = int(item[0]), int(item[1])
            if left == right:
                errors.append(f"self comparator in layer {layer_index}: {item!r}")
                continue
            if not (0 <= left < INPUTS and 0 <= right < INPUTS):
                errors.append(f"wire out of range in layer {layer_index}: {item!r}")
                continue
            left, right = sorted((left, right))
            if left in used or right in used:
                errors.append(f"layer {layer_index} reuses a wire: {item!r}")
            used.add(left)
            used.add(right)
            layer.append((left, right))
        if layer:
            layers.append(layer)
    return layers, errors


def _looks_like_pair(value) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    return all(isinstance(item, int) and not isinstance(item, bool) for item in value)


def _apply_network(mask: int, comparators: list[tuple[int, int]]) -> int:
    for left, right in comparators:
        left_bit = (mask >> left) & 1
        right_bit = (mask >> right) & 1
        if left_bit > right_bit:
            mask ^= (1 << left) | (1 << right)
    return mask


def _sorted_masks() -> set[int]:
    return {((1 << ones) - 1) << (INPUTS - ones) for ones in range(INPUTS + 1)}


def _bits(mask: int) -> str:
    return "".join("1" if (mask >> index) & 1 else "0" for index in range(INPUTS))


def _result(
    valid: bool,
    layers: list[list[tuple[int, int]]],
    layer_sizes: list[int],
    size: int,
    depth: int,
    failed_inputs: int,
    counterexamples: list[str],
    errors: list[str],
) -> dict:
    return {
        "valid": valid,
        "layers": layers,
        "layer_sizes": layer_sizes,
        "size": size,
        "depth": depth,
        "failed_inputs": failed_inputs,
        "counterexamples": counterexamples,
        "errors": errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
