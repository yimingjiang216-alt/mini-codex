from csvlite import parse


def test_quoted_comma_is_one_field():
    # 引号内的逗号属于字段内容，不应作为分隔符
    assert parse('a,"b,c",d') == [["a", "b,c", "d"]]


def test_quoted_delimiter_multiple_rows():
    text = 'name,note\n"Zhang, Wei","says \"hi\""'
    assert parse(text) == [["name", "note"], ["Zhang, Wei", 'says "hi"']]


def test_escaped_quote_inside_quotes():
    assert parse('"a""b",c') == [['a"b', "c"]]


def test_unquoted_fields_still_work():
    assert parse("a,b\n1,2") == [["a", "b"], ["1", "2"]]
