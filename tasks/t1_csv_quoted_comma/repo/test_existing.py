from csvlite import parse


def test_plain_csv():
    assert parse("a,b,c\n1,2,3") == [["a", "b", "c"], ["1", "2", "3"]]


def test_ignores_blank_lines():
    assert parse("a,b\n\n1,2") == [["a", "b"], ["1", "2"]]
