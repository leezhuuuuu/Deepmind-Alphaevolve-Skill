"""Online bin-packing heuristic under evolution."""


# EVOLVE-BLOCK-START
def choose_bin(item, remaining_capacities):
    """Choose a bin for one online item; remaining_capacities are free spaces in capacity-100 bins."""
    for index, remaining in enumerate(remaining_capacities):
        if item <= remaining:
            return index
    return -1
# EVOLVE-BLOCK-END
