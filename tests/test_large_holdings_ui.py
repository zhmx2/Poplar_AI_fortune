import pandas as pd

from app.ui.sec_holdings import STYLER_SAFE_CELL_LIMIT, _can_style


def test_large_dataframe_bypasses_pandas_styler():
    columns = 10
    rows = STYLER_SAFE_CELL_LIMIT // columns + 1
    large = pd.DataFrame(0, index=range(rows), columns=range(columns))
    assert not _can_style(large)


def test_small_dataframe_keeps_option_highlighting():
    small = pd.DataFrame({"security_type": ["OPTION"], "value": [1.0]})
    assert _can_style(small)
