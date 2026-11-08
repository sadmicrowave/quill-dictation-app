"""Excel's own object model on Windows (COM): wrapped text and the filter calls ``quill.bridge.grid`` needs."""

from __future__ import annotations

XL_AND = 1
XL_FILTER_VALUES = 7


def wrap_text(cell_api) -> None:
    cell_api.WrapText = True


def set_autofilter(sheet_api, table_api, first_col: int, criteria) -> None:
    """Show only the rows that match *criteria* (``{column: ColumnFilter}``)."""
    if sheet_api.AutoFilterMode:
        sheet_api.AutoFilterMode = False
    for col, flt in criteria.items():
        _apply(table_api, col - first_col + 1, flt)


def clear_autofilter(sheet_api) -> None:
    if sheet_api.FilterMode:
        sheet_api.ShowAllData()


def _apply(rng_api, field: int, flt) -> None:
        if flt.values:
            if len(flt.values) == 1:
                rng_api.AutoFilter(Field=field, Criteria1="=" + flt.values[0])
            else:
                rng_api.AutoFilter(Field=field, Criteria1=list(flt.values),
                                   Operator=XL_FILTER_VALUES)
            return
        tests = [f"{op}{limit:g}" for op, limit in flt.comparisons]
        if len(tests) == 1:
            rng_api.AutoFilter(Field=field, Criteria1=tests[0])
        else:
            rng_api.AutoFilter(Field=field, Criteria1=tests[0], Operator=XL_AND,
                               Criteria2=tests[1])
