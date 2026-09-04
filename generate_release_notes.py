"""Generates release notes for `gh release create` from the git commit
messages since the last tag, so every release documents what changed and
why instead of a generic placeholder."""
import subprocess


def last_tag():
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return None


def commit_subjects(since_tag):
    range_spec = f"{since_tag}..HEAD" if since_tag else "HEAD"
    out = subprocess.check_output(["git", "log", range_spec, "--format=%s"], text=True)
    return [line for line in out.splitlines() if line.strip()]


def main():
    tag = last_tag()
    subjects = commit_subjects(tag)
    print("## What changed")
    print()
    if not subjects:
        print("No code changes since the last release.")
    else:
        for subject in subjects:
            print(f"- {subject}")


if __name__ == "__main__":
    main()
