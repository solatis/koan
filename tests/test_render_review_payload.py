# Characterization tests for _render_review_payload.
#
# Reference: frontend/src/App.tsx formatReviewMessage (lines 797-850, now deleted).
# The Python port must be byte-identical for the orchestrator's pattern-match
# logic ('I\'ve reviewed', 'approve it as-is') to work in both yolo and interactive runs.
#
# Fixtures are derived by tracing through the JS function manually and confirming
# the Python output matches.

from koan.web.mcp_endpoint import _render_review_payload, _yolo_artifact_review_response


# -- Branch 1: Approval (no comments, no summary) ----------------------------

def test_approval_empty_payload():
    result = _render_review_payload("plan.md", {"summary": "", "comments": []})
    expected = "I've reviewed `plan.md` and approve it as-is. No changes requested."
    assert result == expected


def test_approval_missing_keys():
    """Missing summary/comments keys treated as empty -- still approval."""
    result = _render_review_payload("plan.md", {})
    expected = "I've reviewed `plan.md` and approve it as-is. No changes requested."
    assert result == expected


def test_approval_whitespace_only_summary():
    """Whitespace-only summary strips to empty -- still approval."""
    result = _render_review_payload("plan.md", {"summary": "   ", "comments": []})
    expected = "I've reviewed `plan.md` and approve it as-is. No changes requested."
    assert result == expected


# -- Branch 2: Structured (inline comments, no summary) ----------------------

def test_structured_one_comment():
    payload = {
        "summary": "",
        "comments": [
            {"blockIndex": 1, "text": "Fix this line", "blockPreview": "some text here"},
        ],
    }
    result = _render_review_payload("plan.md", payload)
    expected = (
        "I've reviewed `plan.md`. For each inline comment below, edit the cited"
        " section of the file to address it. Preserve everything not called out."
        " When all comments are addressed, call `koan_yield` again so I can"
        " confirm or give another pass."
        "\n"
        "\nOn the section:"
        "\n> some text here"
        "\n"
        "\n- Fix this line"
    )
    assert result == expected


def test_structured_two_comments_same_block():
    """Two comments on the same blockIndex are grouped under one section header."""
    payload = {
        "summary": "",
        "comments": [
            {"blockIndex": 0, "text": "First comment", "blockPreview": "preview text"},
            {"blockIndex": 0, "text": "Second comment", "blockPreview": "preview text"},
        ],
    }
    result = _render_review_payload("plan.md", payload)
    # Both comments appear under one 'On the section:' block
    assert result.count("On the section:") == 1
    assert "- First comment" in result
    assert "- Second comment" in result


def test_structured_two_comments_different_blocks_sorted():
    """Comments on different blocks are sorted ascending by blockIndex."""
    payload = {
        "summary": "",
        "comments": [
            {"blockIndex": 3, "text": "Later block", "blockPreview": "block 3"},
            {"blockIndex": 1, "text": "Earlier block", "blockPreview": "block 1"},
        ],
    }
    result = _render_review_payload("plan.md", payload)
    # block 1 must appear before block 3
    idx_1 = result.index("block 1")
    idx_3 = result.index("block 3")
    assert idx_1 < idx_3


def test_structured_preview_multiline():
    """Multi-line preview: each line prefixed with '> '."""
    payload = {
        "summary": "",
        "comments": [
            {"blockIndex": 0, "text": "Fix it", "blockPreview": "line one\nline two"},
        ],
    }
    result = _render_review_payload("plan.md", payload)
    assert "> line one" in result
    assert "> line two" in result


def test_structured_comment_multiline():
    """Multi-line comment text: first line as '- first', rest as '  continuation'."""
    payload = {
        "summary": "",
        "comments": [
            {"blockIndex": 0, "text": "first line\ncontinuation", "blockPreview": "p"},
        ],
    }
    result = _render_review_payload("plan.md", payload)
    assert "- first line" in result
    assert "  continuation" in result


# -- Branch 3: Free-form (summary only, no comments) -------------------------

def test_free_form_summary_only():
    payload = {
        "summary": "Please restructure section 2",
        "comments": [],
    }
    result = _render_review_payload("plan.md", payload)
    expected = (
        "I've reviewed `plan.md`. Apply the feedback below, then call `koan_yield`"
        " again so I can confirm or give another pass."
        "\n"
        "\n**Summary:** Please restructure section 2"
    )
    assert result == expected


# -- Branch 4: Combined (comments + summary) ----------------------------------

def test_combined_comments_and_summary():
    payload = {
        "summary": "Overall looks good",
        "comments": [
            {"blockIndex": 0, "text": "Change X", "blockPreview": "line one\nline two"},
        ],
    }
    result = _render_review_payload("plan.md", payload)
    # Opener is the structured (comments) opener, not free-form
    assert "For each inline comment below" in result
    # Apply feedback opener should NOT appear (that's free-form only)
    assert "Apply the feedback below" not in result
    # Summary is appended at the end
    assert "**Summary:** Overall looks good" in result
    # Comment is present
    assert "- Change X" in result
    # Preview lines
    assert "> line one" in result


# -- yolo response matches approval branch ------------------------------------

def test_yolo_matches_approval_branch():
    """_yolo_artifact_review_response must produce the same string as the
    approval branch of _render_review_payload so orchestrators see identical
    input in yolo and interactive runs."""
    path = "plan.md"
    yolo = _yolo_artifact_review_response(path)
    approval = _render_review_payload(path, {"summary": "", "comments": []})
    assert yolo == approval


# -- Different artifact paths -------------------------------------------------

def test_path_with_underscores():
    result = _render_review_payload("my_plan.md", {})
    assert "`my_plan.md`" in result


def test_path_propagated_to_message():
    result = _render_review_payload("brief.md", {
        "summary": "needs work",
        "comments": [],
    })
    assert "`brief.md`" in result
