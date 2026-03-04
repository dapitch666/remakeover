"""pytest configuration: global fixtures and AppTest framework patches."""

import streamlit.testing.v1.element_tree as _et

# ---------------------------------------------------------------------------
# Workaround for Streamlit AppTest bug (Streamlit ≤ 1.54):
# ButtonGroup.indices iterates over self.value which can be None when
# st.segmented_control has no default selection (no item selected).
# The fix: return an empty list instead of crashing with TypeError.
# ---------------------------------------------------------------------------


def _patched_indices(self: "_et.ButtonGroup") -> list:
    val = self.value  # may be None for un-selected segmented_control
    if val is None:
        return []
    # segmented_control (single-select) returns a plain string; wrap it so the
    # list-comprehension below doesn't iterate over individual characters.
    items = val if isinstance(val, list | tuple) else [val]
    return [self.options.index(self.format_func(v)) for v in items]


_et.ButtonGroup.indices = property(_patched_indices)
