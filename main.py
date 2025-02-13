import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import re
import logging
from github import Github
import os
import sys

class GithubClient:
    def __init__(self, token):
        self.github = Github(token)

    def get_branches_by_regex(self, repo_owner, repo_name, regex_pattern):
        logging.debug(f"Performing request to github")
        repo = self.github.get_repo(f"{repo_owner}/{repo_name}")
        rate_limit = self.github.get_rate_limit()
        logging.info(rate_limit)
        branches = [
            branch.name.lower() for branch in repo.get_branches()
        ]

        logging.debug(f"Repo {repo_name} has {len(branches)} branches total")
        regexes = [regex.replace(' ', '') for regex in  regex_pattern.split(",")]
        matching_branches = []
        for branch in branches:
            for regex in regexes:
                if re.search(regex, branch):
                    matching_branches.append({"name": branch, "name_normalized": self.normalize_branch(branch)})
                    break
        logging.info(f"Total matching branches: {len(matching_branches)}")
        logging.debug(f"Matching branches: {matching_branches}")
        return matching_branches

    @staticmethod
    def normalize_branch(branch):
        normalized_name = branch.lower()
        normalized_name = re.sub(r'[^a-z0-9-]', '-', normalized_name)
        normalized_name = normalized_name[:30]
        normalized_name = normalized_name.strip('-')
        return normalized_name


class Plugin(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.plugin_token = kwargs.pop('plugin_token', None)
        self.github_client = GithubClient(kwargs.pop('github_token', None))
        super().__init__(*args, **kwargs)

    def args(self):
        return json.loads(self.rfile.read(int(self.headers.get('Content-Length'))))

    def reply(self, reply):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode("UTF-8"))

    def forbidden(self):
        self.send_response(403)
        self.end_headers()


    def unsupported(self):
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + self.plugin_token:
            logging.error(f"Invalid token")
            self.forbidden()
            return()

        if self.path == '/api/v1/getparams.execute':
            args = self.args()
            logging.debug(f"Got args: {args}")
            repository_owner = args['input']['parameters']['repositoryOwner']
            repository_name = args['input']['parameters']['repositoryName']
            branch_match = args['input']['parameters']['branchMatch']
            branches = self.github_client.get_branches_by_regex(repo_owner=repository_owner, repo_name=repository_name,
                                                         regex_pattern=branch_match)
            reply = {
                "output": {
                    "parameters": [
                        {
                            "total": len(branches),
                            "branches": branches
                        }
                    ]
                }
            }
            logging.debug(f"Reply: {reply}")
            self.reply(reply)
        else:
            self.unsupported()


if __name__ == '__main__':
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    auth_token = os.environ['PLUGIN_TOKEN']
    gh_token = os.environ['GITHUB_TOKEN']
    if not auth_token or not gh_token:
        raise ValueError("Both PLUGIN_TOKEN and GITHUB_TOKEN environment variables must be set.")

    logging.basicConfig(
        format="{asctime} [{levelname}] {message}",
        style="{",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=log_level,
        stream=sys.stdout
    )

    def handler(*args, **kwargs):
        Plugin(github_token=gh_token, plugin_token=auth_token, *args, **kwargs)

    httpd = HTTPServer(('', 4355), handler)
    logging.info(f"Plugin started.")
    httpd.serve_forever()
