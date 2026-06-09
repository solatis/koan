# Unit tests for koan.tools.line_anchors -- the stateless hash-anchored protocol.
#
# Covers the pure functions shared by read/edit and artifact view/edit:
# anchor derivation + collision ordinals, anchored rendering, and edit
# application (replace/range/insert/delete + resolution errors).

from __future__ import annotations

from koan.tools.line_anchors import (
    ANCHOR_DELIMITER as D,
    apply_anchored_edit,
    compute_anchors,
    fnv1a32,
    render_anchored,
)


# -- fnv1a32 / compute_anchors ----------------------------------------------- #


def test_fnv1a32_is_8_hex_and_deterministic():
    h = fnv1a32("def process(data):")
    assert len(h) == 8
    assert all(c in "0123456789abcdef" for c in h)
    assert fnv1a32("def process(data):") == h  # pure


def test_compute_anchors_unique_lines_get_bare_hash():
    anchors = compute_anchors(["a", "b", "c"])
    assert anchors == [fnv1a32("a"), fnv1a32("b"), fnv1a32("c")]


def test_compute_anchors_duplicates_get_ordinals():
    anchors = compute_anchors(["x", "x", "x"])
    base = fnv1a32("x")
    assert anchors == [base, f"{base}~2", f"{base}~3"]


def test_compute_anchors_all_unique_within_file():
    lines = ["", "}", "", "}", "    return"]
    anchors = compute_anchors(lines)
    assert len(set(anchors)) == len(anchors)  # every anchor distinct


# -- render_anchored --------------------------------------------------------- #


def test_render_anchored_format_and_line_numbers():
    out = render_anchored("alpha\nbeta\n")
    rows = out.splitlines()
    assert rows[0] == f"1\t{fnv1a32('alpha')}{D}alpha"
    assert rows[1] == f"2\t{fnv1a32('beta')}{D}beta"


def test_render_anchored_slice_keeps_absolute_line_numbers_and_full_file_anchors():
    content = "\n".join(f"line{i}" for i in range(10)) + "\n"
    out = render_anchored(content, offset=3, limit=2)
    rows = out.splitlines()
    assert len(rows) == 2
    assert rows[0].startswith("4\t")  # absolute, 1-based
    # Anchor is computed over the whole file, so it matches a full-file compute.
    full = compute_anchors(content.splitlines())
    assert rows[0] == f"4\t{full[3]}{D}line3"


# -- apply_anchored_edit ----------------------------------------------------- #


def _tok(content: str, i: int) -> str:
    lines = content.splitlines()
    return f"{compute_anchors(lines)[i]}{D}{lines[i]}"


def test_replace_single_line():
    content = "a\nb\nc\n"
    out, err = apply_anchored_edit(content, _tok(content, 1), "B")
    assert err is None
    assert out == "a\nB\nc\n"


def test_replace_range_inclusive():
    content = "a\nb\nc\nd\n"
    out, err = apply_anchored_edit(content, _tok(content, 1), "X\nY", end_anchor=_tok(content, 2))
    assert err is None
    assert out == "a\nX\nY\nd\n"


def test_replace_empty_text_deletes_line():
    content = "a\nb\nc\n"
    out, err = apply_anchored_edit(content, _tok(content, 1), "")
    assert err is None
    assert out == "a\nc\n"


def test_insert_before_and_after():
    content = "a\nb\n"
    before, _ = apply_anchored_edit(content, _tok(content, 1), "pre", edit_type="insert_before")
    assert before == "a\npre\nb\n"
    after, _ = apply_anchored_edit(content, _tok(content, 0), "post", edit_type="insert_after")
    assert after == "a\npost\nb\n"


def test_no_trailing_newline_preserved():
    content = "a\nb"  # no final newline
    out, err = apply_anchored_edit(content, _tok(content, 1), "B")
    assert err is None
    assert out == "a\nB"  # still no trailing newline


def test_anchor_not_found_errors():
    out, err = apply_anchored_edit("a\nb\n", "deadbeef§a", "x")
    assert out is None
    assert "not found" in err


def test_content_mismatch_errors():
    content = "a\nb\n"
    anchor = compute_anchors(content.splitlines())[0]
    out, err = apply_anchored_edit(content, f"{anchor}{D}WRONG", "x")
    assert out is None
    assert "mismatch" in err


def test_malformed_anchor_errors():
    out, err = apply_anchored_edit("a\n", "not-a-hash§a", "x")
    assert out is None
    assert "malformed" in err


def test_unknown_edit_type_errors():
    content = "a\n"
    out, err = apply_anchored_edit(content, _tok(content, 0), "x", edit_type="nope")
    assert out is None
    assert "edit_type" in err


def test_end_anchor_before_anchor_errors():
    content = "a\nb\nc\n"
    out, err = apply_anchored_edit(content, _tok(content, 2), "x", end_anchor=_tok(content, 0))
    assert out is None
    assert "at or after" in err


def test_end_anchor_with_insert_errors():
    content = "a\nb\n"
    out, err = apply_anchored_edit(
        content, _tok(content, 0), "x", end_anchor=_tok(content, 1), edit_type="insert_after"
    )
    assert out is None
    assert "end_anchor" in err
