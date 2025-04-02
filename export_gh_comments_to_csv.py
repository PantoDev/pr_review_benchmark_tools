import re
import sys

import click
import pandas as pd
import requests

from config import GITHUB_TOKEN

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_pr_reviews(api_url: str, pr_url: str):
    results = []
    pull_response = requests.get(api_url.replace('/comments', ''),
                                 headers=headers)
    if pull_response.status_code != 200:
        print("ERROR: ", pull_response.json())
        pull_response.raise_for_status()
    pull_data = pull_response.json()
    pr_description = pull_data['body']

    while api_url:
        comment_response = requests.get(api_url, headers=headers)
        print("this is response", comment_response)

        comment_datas = comment_response.json()

        for data in comment_datas:

            if '[bot]' not in data['user']['login']:
                continue

            results.append({
                "Repository": re.sub(r'/pull/\d+', '', pr_url),
                "PR No": pr_url.split("/")[-1],
                "Pr Description": pr_description,
                "Suggestion": data['body'],
                "Comment By": data['user']['login'],
                "Date": data['created_at'],
                "Small Diff": data['diff_hunk']
            })
        link_header = comment_response.headers.get('Link')
        api_url = extract_next_link(link_header)

    # https://api.github.com/repos/microsoft/vscode/pulls

    return results


def extract_next_link(link_header):
    if not link_header:
        return None
    links = link_header.split(',')
    for link in links:
        url, rel = link.split(';')
        url = url.strip('<>')
        if 'rel="next"' in rel:
            return url
    return None


def get_pull_requests(api_url: str):
    results = []
    response = requests.get(api_url, headers=headers)
    datas = response.json()

    for data in datas:

        pr_data = get_pr_reviews(data['url'] + '/comments', data['html_url'])
        if pr_data:
            results.append(pr_data)

    return results


@click.command()
@click.option("--pr_url", type=str, help="GitHub Pull Request URL")
@click.option("--file_path", type=str, help="Path to the csv file")
def main(pr_url, file_path):
    if pr_url:
        api_url = re.sub(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)',
                         r'api.github.com/repos/\1/\2/pulls/\3/comments',
                         pr_url)
        json_data = get_pr_reviews(api_url, pr_url)
    elif file_path:
        df = pd.read_csv(file_path)
        json_data = []
        for index, row in df.iterrows():
            pr_url = row['Cloned PR Link']
            api_url = re.sub(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)',
                             r'api.github.com/repos/\1/\2/pulls/\3/comments',
                             pr_url)
            pr_data = get_pr_reviews(api_url, pr_url)
            if pr_data:
                json_data.extend(pr_data)

    else:
        print("Error: Enter either --pr_url or \
                  --repo_url or pr_records.csv file required")
        sys.exit(1)

    df = pd.DataFrame(json_data)
    output_file = f"{file_path.strip('.csv')}_bot_comment_data.csv"  \
        if file_path else f"{pr_url.split('/')[-1]}.bot_comment_data.csv"

    df.to_csv(output_file, index=False)
    print("Quality analysis of data done.")


if __name__ == '__main__':
    main()
