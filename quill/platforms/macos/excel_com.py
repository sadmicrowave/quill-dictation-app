"""Excel's own object model on a Mac (AppleScript through appscript): wrapped text and the filter calls ``quill.bridge.grid`` needs."""

from __future__ import annotations


def wrap_text(cell_api) -> None:
    cell_api.wrap_text.set(True)


def set_autofilter(sheet_api, table_api, first_col: int, criteria) -> None:
    """Show only the rows that match *criteria* (``{column: ColumnFilter}``)."""
    if sheet_api.autofilter_mode.get():
        sheet_api.autofilter_mode.set(False)
    for col, flt in criteria.items():
        _apply(table_api, col - first_col + 1, flt)


def clear_autofilter(sheet_api) -> None:
    if sheet_api.filter_mode.get():
        sheet_api.show_all_data()


def _apply(rng_api, field: int, flt) -> None:
    from appscript import k
    if flt.values:
        rng_api.autofilter(field=field, criteria1="=" + flt.values[0])
        if len(flt.values) > 1:   # AppleScript has no value-list form; OR the first two
            rng_api.autofilter(field=field, criteria1="=" + flt.values[0], operator=k.autofilter_or,
                               criteria2="=" + flt.values[1])
        return
    tests = [f"{op}{limit:g}" for op, limit in flt.comparisons]
    if len(tests) == 1:
        rng_api.autofilter(field=field, criteria1=tests[0])
    else:
        rng_api.autofilter(field=field, criteria1=tests[0], operator=k.autofilter_and,
                           criteria2=tests[1])
