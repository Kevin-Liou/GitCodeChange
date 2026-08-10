import git, os, re, shutil
from datetime import datetime


def export_diff_files(repo_path, sha1, output_path):
    # Initialize Git repository and commit objects
    repo = git.Repo(repo_path)
    assert not repo.bare
    # Get current commit
    commit = repo.commit(sha1)
    # Get parent commit
    parent_commit = commit.parents[0]
    # Get commit message
    commit_message = commit.message

    # Calculate diff between the commit and its parent
    diff = parent_commit.diff(commit, create_patch=True)

    # Separate changed, added, and deleted files from the diff
    changed_files = list(diff.iter_change_type("M")) + list(diff.iter_change_type("R"))
    added_files = list(diff.iter_change_type("A"))
    deleted_files = list(diff.iter_change_type("D"))

    # Create directories to store modified and original files
    output_folder_name = "CodeChange_" + sha1
    mod_dir = os.path.join(output_path, output_folder_name, "mod")
    org_dir = os.path.join(output_path, output_folder_name, "org")
    os.makedirs(mod_dir, exist_ok=True)
    os.makedirs(org_dir, exist_ok=True)

    # Save changed files (new and old versions)
    for diff_file in changed_files:
        new_blob = diff_file.b_blob
        old_blob = diff_file.a_blob

        if new_blob is None:
            continue

        new_file_path = os.path.join(mod_dir, new_blob.path)
        old_file_path = os.path.join(org_dir, old_blob.path)

        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(new_file_path, "wb") as f:
            f.write(new_blob.data_stream.read())
        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())

    # Save added files
    for diff_file in added_files:
        new_blob = diff_file.b_blob

        new_file_path = os.path.join(mod_dir, new_blob.path)
        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

        with open(new_file_path, "wb") as f:
            f.write(new_blob.data_stream.read())

    # Save deleted files
    for diff_file in deleted_files:
        old_blob = diff_file.a_blob

        old_file_path = os.path.join(org_dir, old_blob.path)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())

    # Create note.txt file and write the file lists
    write_note_file(os.path.join(output_path, output_folder_name), changed_files, added_files, deleted_files, sha1, commit_message)


def export_uncommitted_changes(repo_path, output_path):
    # Initialize Git repository
    repo = git.Repo(repo_path)
    assert not repo.bare

    current_path = output_path
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    output_folder_name = "CodeChange_" + timestamp

    # Get head_commit_diff and untracked_files changes
    staged_diff = repo.index.diff(None) + repo.index.diff(repo.head.commit) # Can get status but b_blob is none
    head_commit_diff = repo.head.commit.diff(None, create_patch=True) # Can't get status but can get b_blob
    untracked_files = repo.untracked_files

    changed_files = []
    added_files = []
    deleted_files = []

    # Add untracked_files to added_files list
    for untracked_file in untracked_files:
        added_files.append(untracked_file)

    # Match staged and head commit diffs to find changed, added, and deleted files
    for staged_diff_file in staged_diff:
        for head_commit_diff_file in head_commit_diff:
            if staged_diff_file.change_type == "M":
                if staged_diff_file.a_path == head_commit_diff_file.a_path:
                    changed_files.append(head_commit_diff_file)
            elif staged_diff_file.change_type == "A":
                if staged_diff_file.a_path == head_commit_diff_file.a_path:
                    added_files.append(head_commit_diff_file)
            elif staged_diff_file.change_type == "D":
                if staged_diff_file.a_path == head_commit_diff_file.a_path:
                    deleted_files.append(head_commit_diff_file)
            elif staged_diff_file.change_type == "R":
                if staged_diff_file.a_path == head_commit_diff_file.a_path:
                    deleted_files.append(head_commit_diff_file)

    if len(changed_files) == 0 and len(added_files) == 0 and len(deleted_files) == 0:
        return False

    # Create directories for modified and original files
    mod_dir = os.path.join(current_path, output_folder_name, "mod")
    org_dir = os.path.join(current_path, output_folder_name, "org")
    os.makedirs(os.path.join(mod_dir), exist_ok=True)
    os.makedirs(os.path.join(org_dir), exist_ok=True)

    # Save changed files (new and old versions)
    for diff_file in changed_files:
        new_blob = diff_file.b_blob
        old_blob = diff_file.a_blob

        new_file_path = os.path.join(mod_dir, new_blob.path)
        old_file_path = os.path.join(org_dir, old_blob.path)

        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        shutil.copy(os.path.join(repo_path, new_blob.path), os.path.dirname(new_file_path))
        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())

    # Save added files
    dir_list = []
    for diff_file in added_files:
        if os.path.isdir(os.path.join(repo_path, diff_file)):
            dir_list.append(diff_file)
            continue

        new_file_path = os.path.join(mod_dir, diff_file)
        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

        shutil.copy(os.path.join(repo_path, diff_file), os.path.dirname(new_file_path))

    # Remove directories from added_files
    for dir in dir_list:
        added_files.remove(dir)

    # Save deleted files
    for diff_file in deleted_files:
        old_blob = diff_file.a_blob

        old_file_path = os.path.join(org_dir, old_blob.path)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())

    # Create note.txt file and write the file lists
    write_note_file(os.path.join(output_path, output_folder_name), changed_files, added_files, deleted_files, sha1 = None, commit_message = None)
    return True


# Check if a given string is a valid SHA-1 hash
def is_valid_sha1(sha1):
    if len(sha1) != 40:
        return False
    if not re.match(r"[0-9a-fA-F]{40}", sha1):
        return False
    return True


def is_sha1_exist(repo_path, sha1):
    # Initialize Git repository and commit objects
    if os.path.isdir(os.path.join(repo_path, ".gitman")):
        for Gitman_folder in os.listdir(os.path.join(repo_path, ".gitman")):
            Gitman_folder = os.path.join(repo_path, ".gitman", Gitman_folder)
            if os.path.isdir(Gitman_folder):
                print("")
    try:
        repo = git.Repo(repo_path)
        assert not repo.bare
        commit = repo.commit(sha1)
        return True
    except ValueError:
        return False # end the function since there's nothing we can do without the commit
    except:
        return False


def is_folder_exist(sha1, output_path):
    mod_dir = os.path.join(output_path, "CodeChange_" + sha1)
    org_dir = os.path.join(output_path, "CodeChange_" + sha1)
    if os.path.isdir(mod_dir) and os.path.isdir(org_dir):
        return True
    return False


# Add note.txt to the given commit
def write_note_file(directory, changed_files, added_files, deleted_files, sha1, commit_message):
    # Create the directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)
    # Write the commit message and file lists to note.txt
    with open(os.path.join(directory, "note.txt"), "w") as note_file:
        if sha1 is not None and commit_message is not None:
            note_file.write("SHA-1: " + sha1 + "\n\n" + commit_message + "\n")
        note_file.write("Changed files:\n")
        for file in changed_files:
            note_file.write(f"{file.a_path}\n")
        note_file.write("\nAdded files:\n")
        for file in added_files:
            note_file.write(f"{file.b_path if hasattr(file, 'b_path') else file}\n")
        note_file.write("\nDeleted files:\n")
        for file in deleted_files:
            note_file.write(f"{file.a_path}\n")