import git, os, re
from datetime import datetime

def export_diff_files(repo_path, sha1):
    repo = git.Repo(repo_path)
    commit = repo.commit(sha1)
    parent_commit = commit.parents[0]

    diff = parent_commit.diff(commit, create_patch=True)

    modified_files = list(diff.iter_change_type("M"))
    added_files = list(diff.iter_change_type("A"))
    deleted_files = list(diff.iter_change_type("D"))

    mod_dir = os.path.join(sha1, "mod")
    org_dir = os.path.join(sha1, "org")
    os.makedirs(mod_dir, exist_ok=True)
    os.makedirs(org_dir, exist_ok=True)

    for diff_file in modified_files:
        new_blob = diff_file.b_blob
        old_blob = diff_file.a_blob

        new_file_path = os.path.join(mod_dir, new_blob.path)
        old_file_path = os.path.join(org_dir, old_blob.path)

        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(new_file_path, "wb") as f:
            f.write(new_blob.data_stream.read())
        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())

    for diff_file in added_files:
        new_blob = diff_file.b_blob

        new_file_path = os.path.join(mod_dir, new_blob.path)
        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

        with open(new_file_path, "wb") as f:
            f.write(new_blob.data_stream.read())

    for diff_file in deleted_files:
        old_blob = diff_file.a_blob

        old_file_path = os.path.join(org_dir, old_blob.path)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())


def export_uncommitted_changes(repo_path):
    repo = git.Repo(repo_path)

    # Add uncommitted changes to the index
    repo.git.add('-A')

    diff = repo.index.diff(None, create_patch=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    mod_dir = os.path.join(timestamp, "mod")
    org_dir = os.path.join(timestamp, "org")
    os.makedirs(mod_dir, exist_ok=True)
    os.makedirs(org_dir, exist_ok=True)

    for diff_file in diff:
        new_blob = diff_file.b_blob if diff_file.b_blob else None
        old_blob = diff_file.a_blob if diff_file.a_blob else None

        if new_blob and new_blob.path and hasattr(new_blob, 'data_stream'):
            new_file_path = os.path.join(mod_dir, new_blob.path)
            os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

            with open(new_file_path, "wb") as f:
                f.write(new_blob.data_stream.read())

        if old_blob and old_blob.path and hasattr(old_blob, 'data_stream'):
            old_file_path = os.path.join(org_dir, old_blob.path)
            os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

            with open(old_file_path, "wb") as f:
                f.write(old_blob.data_stream.read())


def is_valid_sha1(sha1):
    if len(sha1) != 40:
        return False
    if not re.match(r"[0-9a-fA-F]{40}", sha1):
        return False
    return True