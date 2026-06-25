"""Order-9 Golomb ruler construction under evolution."""


ORDER = 9


# EVOLVE-BLOCK-START
def construct_marks():
    """Return 9 increasing integer marks for a Golomb ruler."""
    return [0, 1, 3, 7, 15, 31, 63, 127, 255]
# EVOLVE-BLOCK-END
