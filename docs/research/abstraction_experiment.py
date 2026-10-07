"""Exhaustive finite-model illustration; no desktop or model calls.

Run from the repository root with:
    uv run python docs/research/abstraction_experiment.py
"""

import itertools
import json

STATES = list(itertools.product(range(2), repeat=7))
ACTIONS = ("focus_left", "focus_right", "write_one", "save", "close_modal")


def step(state, action):
    document, focus, modal, left, right, disk_left, disk_right = state
    if action == "close_modal":
        modal = 0
    elif not modal:
        if action == "focus_left":
            focus = 0
        elif action == "focus_right":
            focus = 1
        elif action == "write_one":
            if focus == 0:
                left = 1
            else:
                right = 1
        elif action == "save":
            disk_left, disk_right = left, right
    return document, focus, modal, left, right, disk_left, disk_right


def goal(state):
    return state[0] == 0 and state[5:] == (1, 0)


def coarse(state):
    return state[0], state[2], state[3:5] != state[5:7]


def number_classes(signatures):
    ids = {}
    return {s: ids.setdefault(signatures[s], len(ids)) for s in STATES}


def main():
    pairs = list(itertools.combinations(STATES, 2))
    goal_witness = next(
        (s, t) for s, t in pairs if coarse(s) == coarse(t) and goal(s) != goal(t)
    )
    transition_witness = next(
        (s, t, a)
        for s, t in pairs
        if coarse(s) == coarse(t)
        for a in ACTIONS
        if coarse(step(s, a)) != coarse(step(t, a))
    )
    classes = number_classes({s: (coarse(s), goal(s)) for s in STATES})
    sizes = [len(set(classes.values()))]
    while True:
        refined = number_classes(
            {
                s: (classes[s], tuple(classes[step(s, a)] for a in ACTIONS))
                for s in STATES
            }
        )
        if refined == classes:
            break
        classes = refined
        sizes.append(len(set(classes.values())))
    equivalent_pairs = [(s, t) for s, t in pairs if classes[s] == classes[t]]
    assert all(goal(s) == goal(t) for s, t in equivalent_pairs)
    assert all(
        classes[step(s, a)] == classes[step(t, a)]
        for s, t in equivalent_pairs
        for a in ACTIONS
    )
    print(
        json.dumps(
            {
                "state_fields": [
                    "document",
                    "focus",
                    "modal",
                    "left",
                    "right",
                    "disk_left",
                    "disk_right",
                ],
                "states": len(STATES),
                "actions": list(ACTIONS),
                "coarse_classes": len({coarse(s) for s in STATES}),
                "goal_counterexample": goal_witness,
                "transition_counterexample": transition_witness,
                "refinement_class_counts": sizes,
                "equivalent_pairs_checked": len(equivalent_pairs),
                "transition_comparisons": len(equivalent_pairs) * len(ACTIONS),
                "goal_and_transition_compatibility": "passed",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
