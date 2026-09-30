"""极简点号路径取值：get(data, "a.b.0.c")。"""


class PathNotFound(KeyError):
    """路径不存在时抛出。"""


def get(data, path: str, default=None):
    """按点号路径取值。

    当前只支持纯字典逐层下钻，遇到列表或缺失键就出问题。
    """
    if not path:
        return data
    cur = data
    for part in path.split("."):
        if part not in cur:
            return default
        cur = cur[part]
    return cur
