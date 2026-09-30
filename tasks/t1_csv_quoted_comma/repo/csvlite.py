"""极简 CSV 解析器。"""


def parse(text: str, delimiter: str = ",") -> list[list[str]]:
    """把 CSV 文本解析成二维列表。

    当前实现直接按分隔符切分，还没有处理双引号包裹的字段。
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        row = [cell.strip() for cell in line.split(delimiter)]
        rows.append(row)
    return rows
