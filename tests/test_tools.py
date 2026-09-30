import json

from agents.tools import calculator, query_db, search_docs


def test_search_docs():
    res = search_docs("pricing")
    assert "Gemini 1.5 Flash" in res
    assert "Gemini 1.5 Pro" in res

    not_found = search_docs("xyznonexistenttopic999")
    assert "No documentation found" in not_found


def test_query_db():
    res = query_db("SELECT name, plan FROM users WHERE id = 1;")
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["name"] == "Alice Smith"
    assert data[0]["plan"] == "enterprise"


def test_query_db_error():
    res = query_db("SELECT * FROM non_existent_table;")
    data = json.loads(res)
    assert "error" in data


def test_calculator():
    res = calculator("150 + 50 * 2")
    data = json.loads(res)
    assert data["result"] == 250

    res_parens = calculator("(100 - 20) / 4")
    data_parens = json.loads(res_parens)
    assert data_parens["result"] == 20.0


def test_calculator_safety():
    res = calculator("__import__('os').system('dir')")
    data = json.loads(res)
    assert "error" in data
