from __future__ import annotations

import eval_questions as ev


def test_parse_and_pass():
    qs = ev.parse_questions("# c\n1\tWho is Quill?\tmarta;cartographer/mapmaker\n2\tOther?\n\nbad line\n")
    assert qs == [("1", "Who is Quill?", ["marta", "cartographer/mapmaker"]), ("2", "Other?", [])]
    assert ev.passes("Marta is a Cartographer", qs[0][2])
    assert not ev.passes("Marta only", qs[0][2])
    assert ev.passes("anything", [])
