import csv
import json
import os
import re
import subprocess
import uuid

import requests

from config import GITHUB_EMAIL, GITHUB_TOKEN, GITHUB_USERNAME

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_pr_details(pr_url: str) -> dict:
    """Retrieves pull request details from the GitHub API."""
    match = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not match:
        raise ValueError("Invalid PR URL")
    repo_owner = match.group(1)
    repo_name = match.group(2)
    pr_number = match.group(3)
    pr_api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}"  # noqa: E501
    response = requests.get(pr_api_url, headers=headers)
    response.raise_for_status()
    pr_data = response.json()
    base_branch = pr_data["base"]["ref"]
    pr_sha = pr_data["head"]["sha"]
    base_commit_sha = pr_data["base"]["sha"]
    diff_url = f"https://patch-diff.githubusercontent.com/raw/{repo_owner}/{repo_name}/pull/{pr_number}.diff"  # noqa: E501
    diff_response = requests.get(diff_url, headers=headers)
    diff_response.raise_for_status()
    pr_diff = diff_response.text
    pr_title = pr_data["title"]
    main_branch = pr_data["base"]["repo"]["default_branch"]

    return {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "base_branch": base_branch,
        "pr_sha": pr_sha,
        "base_commit_sha": base_commit_sha,
        "pr_diff": pr_diff,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "pr_body": pr_data["body"],
        "main_branch": main_branch,
    }


def create_new_repo_if_needed(
    *,
    new_repo_name: str,
    new_repo_owner: str,
) -> str:
    new_repo_api_url = f"https://api.github.com/repos/{new_repo_owner}/{new_repo_name}"  # noqa: E501
    new_repo_check_response = requests.get(new_repo_api_url, headers=headers)

    if new_repo_check_response.status_code == 404:
        new_repo_create_url = "https://api.github.com/user/repos"
        new_repo_create_data = {"name": new_repo_name, "private": True}
        new_repo_create_response = requests.post(new_repo_create_url,
                                                 headers=headers,
                                                 json=new_repo_create_data)
        new_repo_create_response.raise_for_status()

    new_repo_url = f"https://{new_repo_owner}:{GITHUB_TOKEN}@github.com/{new_repo_owner}/{new_repo_name}.git"  # noqa: E501
    return new_repo_url


def create_pr(
    *,
    pr_title: str,
    head_branch: str,
    base_branch: str,
    repo_owner: str,
    repo_name: str,
    pr_body: str,
) -> str:
    repo_api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"  # noqa: E501
    create_pr_data = {
        "title": pr_title,
        "head": head_branch,
        "base": base_branch,
        "body": pr_body,
    }
    print(f"Creating PR for branch {create_pr_data}")
    create_pr_response = requests.post(f"{repo_api_url}/pulls",
                                       headers=headers,
                                       json=create_pr_data)
    code = create_pr_response.status_code
    if code != 201:
        print(f"Error creating PR for branch {code}")
        print(create_pr_response.json())
        raise Exception(f"Error creating PR: {code}")
    create_pr_response.raise_for_status()
    pr_url = create_pr_response.json()["html_url"]
    return pr_url


def prepare_git_repo(
    *,
    cwd: str,
    original_main_branch: str,
    original_repo_url: str,
    original_base_branch_sha: str,
    new_repo_name: str,
    new_base_branch: str,
):
    if not os.path.exists(cwd):
        print(f"Cloning {original_repo_url} to {cwd}")
        subprocess_run(["git", "clone", original_repo_url, cwd], check=True)
        subprocess_run(["git", "fetch", "--all"], cwd=cwd, check=True)
    else:
        print(f"Fetching latest changes for {original_repo_url}")
        subprocess_run(["git", "fetch", "--all"], cwd=cwd, check=True)
        subprocess_run(["git", "stash"], cwd=cwd, check=True)
        subprocess_run(["git", "checkout", original_main_branch],
                       cwd=cwd,
                       check=True)
        subprocess_run(["git", "pull"], cwd=cwd, check=True)

    subprocess_run(["git", "checkout", original_base_branch_sha],
                   cwd=cwd,
                   check=True)

    subprocess_run(["git", "checkout", "-b", new_base_branch],
                   cwd=cwd,
                   check=True)

    return new_base_branch, new_repo_name


def reapply_git_diff_to_a_branch(
    *,
    cwd: str,
    new_head_branch_name: str,
    base_branch: str,
    pr_diff: str,
    new_origin: str,
):
    subprocess_run(
        ["git", "checkout", "-b", new_head_branch_name, base_branch],
        cwd=cwd,
        check=True,
    )

    diff_file_path = os.path.join(cwd, "diff.diff")
    with open(diff_file_path, "w", encoding="utf-8") as f:
        f.write(pr_diff)

    apply_diff = subprocess.Popen(["git", "apply", "diff.diff"],
                                  cwd=cwd,
                                  stderr=subprocess.PIPE)
    _, stderr = apply_diff.communicate()

    if apply_diff.returncode != 0:
        raise Exception(f"Failed to apply diff. {stderr.decode()}")

    os.remove(diff_file_path)

    subprocess_run(["git", "add", "."], cwd=cwd, check=True)
    subprocess_run(["git", "config", "user.email", GITHUB_EMAIL],
                   cwd=cwd,
                   check=True)
    subprocess_run(["git", "config", "user.name", "AutoScript"],
                   cwd=cwd,
                   check=True)
    subprocess_run(
        ["git", "commit", "-m", f"Apply changes to {new_head_branch_name}"],
        cwd=cwd,
        check=True,
    )

    subprocess_run(["git", "push", new_origin, base_branch],
                   cwd=cwd,
                   check=True)

    subprocess_run(["git", "push", new_origin, new_head_branch_name],
                   cwd=cwd,
                   check=True)


def add_new_origin_if_needed(
    *,
    cwd: str,
    new_repo_url: str,
):
    new_origin = "new_origin"
    result = subprocess.run(
        ["git", "remote"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    existing_remotes = result.stdout.splitlines()
    if new_origin not in existing_remotes:
        subprocess.run(
            ["git", "remote", "add", new_origin, new_repo_url],
            cwd=cwd,
            check=True,
        )
    return new_origin


def create_duplicate_pr(*, pr_details: dict, dir: str, duplicate_count: int):
    repo_name = pr_details["repo_name"]
    pr_body = pr_details["pr_body"]
    pr_title = pr_details["pr_title"]
    pr_diff = pr_details["pr_diff"]
    original_repo_owner = pr_details["repo_owner"]
    original_repo_name = pr_details["repo_name"]
    original_base_branch = pr_details["base_branch"]
    orginal_pr_no = pr_details["pr_number"]
    original_base_branch_sha = pr_details["base_commit_sha"]
    original_main_branch = pr_details["main_branch"]
    new_base_branch = f"{original_base_branch}_from_pr_{orginal_pr_no}_{uuid.uuid4().hex[:8]}"  # noqa: E501

    assert GITHUB_USERNAME, "Please set YOUR_GITHUB_USERNAME in config.py"
    new_repo_owner = GITHUB_USERNAME

    cwd = f"{dir}/{repo_name}"
    new_repo_name = f"{original_repo_name}-auto-clones"
    original_repo_url = f"https://{new_repo_owner}:{GITHUB_TOKEN}@github.com/{original_repo_owner}/{original_repo_name}.git"  # noqa: E501

    prepare_git_repo(
        cwd=cwd,
        new_repo_name=new_repo_name,
        new_base_branch=new_base_branch,
        original_repo_url=original_repo_url,
        original_main_branch=original_main_branch,
        original_base_branch_sha=original_base_branch_sha,
    )

    new_repo_url = create_new_repo_if_needed(
        new_repo_name=new_repo_name,
        new_repo_owner=new_repo_owner,
    )
    new_origin = add_new_origin_if_needed(
        cwd=cwd,
        new_repo_url=new_repo_url,
    )

    for idx in range(duplicate_count):
        new_head_branch_name = f"{new_base_branch}_index_{idx}_{uuid.uuid4().hex[:8]}"  # noqa: E501
        reapply_git_diff_to_a_branch(
            cwd=cwd,
            new_head_branch_name=new_head_branch_name,
            base_branch=new_base_branch,
            pr_diff=pr_diff,
            new_origin=new_origin,
        )
        new_pr_url = create_pr(
            pr_title=pr_title,
            head_branch=new_head_branch_name,
            base_branch=new_base_branch,
            repo_owner=new_repo_owner,
            repo_name=new_repo_name,
            pr_body=pr_body,
        )
        yield new_pr_url


def subprocess_run(args, **kwargs):
    print(f"Running: {' '.join(args)}")
    return subprocess.run(args, **kwargs)


def main():
    target_file = "clone_repos.json"
    with open(target_file) as f:
        data = json.loads(f.read())
        pr_urls = data.get("pr_urls", [])
        duplicate_count = data.get("duplicate_count", 2)
        output_file = data.get("output_file", "pr_records.csv")

    if not pr_urls:
        print("No PR URLs found in the clone_repos.json file.")
        return
    temp_dir = "./tmp"
    with open(output_file, "w+", newline="") as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["Original PR Link", "Cloned PR Link"])
        for pr_url in pr_urls:
            try:
                pr_details = get_pr_details(pr_url)
                duplicate_pr_gen = create_duplicate_pr(
                    pr_details=pr_details,
                    dir=temp_dir,
                    duplicate_count=duplicate_count,
                )
                for new_pr_url in duplicate_pr_gen:
                    csv_writer.writerow([pr_url, new_pr_url])
                print(f"Successfully processed {pr_url}")
            except Exception as e:
                print(f"Error processing {pr_url}: {e}")
                raise e
    print("PR processing completed.")


if __name__ == "__main__":
    main()
