
import json
import os
import subprocess
import sys
import urllib.request

from pathlib import Path
from urllib.error import HTTPError, URLError


API_URL = (
    "https://generativelanguage.googleapis.com"
    "/v1beta/interactions"
)

MODEL = os.environ.get(
    "GEMINI_MODEL", "gemini-3.5-flash-lite"
)

PROMPT_FILE = Path(__file__).with_name(
    "review_prompt.txt"
)

MAX_DIFF_SIZE = 100_000


def get_diff():
    """Get local Git changes for relevant files."""

    return subprocess.check_output(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "HEAD",
            "--",
            "src/",
            "Dockerfile",
            "package.json",
            "package-lock.json",
            ".github/workflows/",
            "scripts/",
        ],
        text=True,
    )


def github_request(
    endpoint,
    method="GET",
    payload=None,
    accept="application/vnd.github+json",
):
    """Send an authenticated request to the GitHub API."""

    request = urllib.request.Request(
        f"https://api.github.com/{endpoint}",
        data=(
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        ),
        headers={
            "Authorization": (
                f"Bearer {os.environ['GITHUB_TOKEN']}"
            ),
            "Accept": accept,
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )

    with urllib.request.urlopen(
        request, timeout=60
    ) as response:
        return response.read().decode("utf-8")


def get_pr_diff():
    """Retrieve the PR diff without executing PR code."""

    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])

    return github_request(
        f"repos/{repository}/pulls/{pr_number}",
        accept="application/vnd.github.diff",
    )


def review_code(diff):
    """Send the Git diff to the Gemini API."""

    prompt = PROMPT_FILE.read_text(
        encoding="utf-8"
    )

    payload = {
        "model": MODEL,
        "input": (
            prompt
            + "\n\n<git_diff>\n"
            + diff
            + "\n</git_diff>"
        ),
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request, timeout=120
    ) as response:
        return json.load(response)


def extract_review(result):
    """Extract the review text from the API response."""

    if result.get("status") != "completed":
        raise RuntimeError(
            "AI review did not complete."
        )

    texts = []

    for step in result.get("steps", []):
        if step.get("type") == "model_output":
            for content in step.get("content", []):
                if content.get("type") == "text":
                    texts.append(content["text"])

    if not texts:
        raise RuntimeError(
            "No review text returned."
        )

    return "\n".join(texts)


def post_pr_comment(review):
    """Publish the AI review as a PR comment."""

    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])

    body = (
        "## AI Code Review\n\n"
        f"**Model:** `{MODEL}`\n\n"
        + review
        + "\n\n---\n"
        "*AI-generated review. "
        "Findings require human validation.*"
    )

    github_request(
        f"repos/{repository}/issues/{pr_number}/comments",
        method="POST",
        payload={"body": body},
    )


def main():
    """Run the AI code review locally or in GitHub Actions."""

    is_ci = os.environ.get("GITHUB_ACTIONS") == "true"

    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY is not set."
        )

    if is_ci:
        print("Running in GitHub Actions mode.")
        diff = get_pr_diff()
    else:
        print("Running in local mode.")
        diff = get_diff()

    if not diff.strip():
        print("No code changes to review.")
        return

    if len(diff.encode("utf-8")) > MAX_DIFF_SIZE:
        raise RuntimeError(
            "Diff exceeds size limit."
        )

    print(f"Running AI code review using {MODEL}...")
    print(f"Diff size: {len(diff.encode('utf-8'))} bytes")
    print()

    result = review_code(diff)
    review = extract_review(result)

    if is_ci:
        post_pr_comment(review)
        print("AI review published successfully.")
    else:
        print(review)


if __name__ == "__main__":
    try:
        main()

    except HTTPError as error:
        print(
            f"API request failed: HTTP {error.code}",
            file=sys.stderr,
        )
        sys.exit(1)

    except URLError as error:
        print(
            f"Connection failed: {error.reason}",
            file=sys.stderr,
        )
        sys.exit(1)

    except (RuntimeError, KeyError, TimeoutError) as error:
        print(
            f"AI review failed: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
