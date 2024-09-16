import openai
import logging
import os
import git
import requests
import sys
from datetime import datetime
import shutil
import time
from requests.auth import HTTPBasicAuth

# Read the OpenAI API key and GitHub token from environment variables
openai.api_key = os.getenv('OPENAI_API_KEY')
github_token = os.getenv('GITHUB_TOKEN')
sn_username = os.getenv('SN_USERNAME')
sn_password = os.getenv('SN_PASSWORD')

# ServiceNow instance URL and endpoint for the incidents table
SN_URL = "https://ansible.service-now.com/api/now/table/incident"
SN_PARAMS = {
    'sysparm_query': 'caller_id.name=Roger Lopez^ORDERBYDESCsys_created_on',
    'sysparm_limit': 1
}
SN_HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

# State ID for "Awaiting User Info". You need to replace this with the actual value.
AWAITING_USER_INFO_STATE_ID = 'your_awaiting_user_info_state_id'

# GitHub repository URL for existing playbooks
EXISTING_PLAYBOOKS_REPO_URL = "https://github.com/cooktheryan/existing-playbooks.git"
EXISTING_PLAYBOOKS_DIR = "existing_playbooks"

# Set up logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger()

def get_most_recent_incident():
    logger.info("Making a call to ServiceNow to check for incidents created by Roger Lopez.")
    try:
        response = requests.get(SN_URL, params=SN_PARAMS, headers=SN_HEADERS, auth=HTTPBasicAuth(sn_username, sn_password))
        logger.info(f"ServiceNow response status code: {response.status_code}")
        response.raise_for_status()

        incidents = response.json().get('result', [])
        logger.info(f"ServiceNow response: {incidents}")

        return incidents[0] if incidents else None
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err}")
    except Exception as err:
        logger.error(f"Other error occurred: {err}")

def ask_openai(description):
    logger.info(f"Generating Ansible playbook for description: {description}")
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an expert in writing Ansible playbooks. You do not need any help in explaining the playbook or how to run the playbook. You return amazing playbooks that always work."},
            {"role": "user", "content": f"Create an Ansible playbook based on this incident description: {description}"}
        ]
    )
    playbook_content = response['choices'][0]['message']['content'].strip()
    logger.info(f"Generated playbook content: {playbook_content}")
    return playbook_content

def format_playbook_content(content):
    # Add YAML document marker '---' at the beginning and remove markdown code block markers
    content = '---\n' + content.replace('```yaml', '').replace('```', '').strip()
    return content

def clone_existing_playbooks_repo():
    if os.path.isdir(EXISTING_PLAYBOOKS_DIR):
        shutil.rmtree(EXISTING_PLAYBOOKS_DIR)
    git.Repo.clone_from(EXISTING_PLAYBOOKS_REPO_URL, EXISTING_PLAYBOOKS_DIR)

def search_existing_playbooks(description):
    clone_existing_playbooks_repo()
    logger.info("Searching for existing playbooks.")
    existing_playbooks = []
    for root, _, files in os.walk(EXISTING_PLAYBOOKS_DIR):
        for file in files:
            if file.endswith(".yml") or file.endswith(".yaml"):
                with open(os.path.join(root, file), 'r') as f:
                    playbook_content = f.read()
                    existing_playbooks.append(playbook_content)

    for playbook in existing_playbooks:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in Ansible playbooks. Evaluate if the provided playbook content matches the given incident description."},
                {"role": "user", "content": f"Incident description: {description}"},
                {"role": "assistant", "content": playbook}
            ]
        )
        evaluation = response['choices'][0]['message']['content'].strip()
        if "matches" in evaluation.lower():
            return playbook

    return None

def create_pull_request(branch_name, file_path, playbook_content):
    repo_url = 'git@github.com:cooktheryan/wranger-out.git'
    repo_dir = 'repo'
    pr_url = "https://api.github.com/repos/cooktheryan/wranger-out/pulls"

    try:
        # Clone the repository
        logger.info(f"Cloning repository from {repo_url}")
        git.Repo.clone_from(repo_url, repo_dir, branch='main')
        repo = git.Repo(repo_dir)

        # Create a new branch
        logger.info(f"Creating new branch: {branch_name}")
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()

        # Write the formatted playbook content to a file
        with open(f"{repo_dir}/{file_path}", "w") as file:
            file.write(playbook_content)

        # Commit and push changes
        repo.index.add([file_path])
        repo.index.commit("Add generated playbook")
        origin = repo.remote(name='origin')
        origin.push(branch_name)

        # Create a pull request
        pr_title = "Add generated playbook"
        pr_body = "This PR contains a generated Ansible playbook."
        headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        payload = {
            'title': pr_title,
            'body': pr_body,
            'head': branch_name,
            'base': 'main'
        }
        logger.info(f"Creating pull request with payload: {payload}")
        response = requests.post(pr_url, json=payload, headers=headers)
        logger.info(f"Pull request creation response status code: {response.status_code}")
        if response.status_code == 201:
            return response.json()
        else:
            logger.error(f"Failed to create pull request: {response.text}")
            return None
    finally:
        # Ensure the local repository directory is removed
        if os.path.isdir(repo_dir):
            shutil.rmtree(repo_dir)

def update_incident_state(incident_sys_id, state_id, comment=None):
    update_url = f"{SN_URL}/{incident_sys_id}"
    data = {
        'state': state_id
    }
    if comment:
        data['comments'] = comment

    logger.info(f"Updating incident {incident_sys_id} to state {state_id}.")
    try:
        response = requests.patch(update_url, json=data, headers=SN_HEADERS, auth=HTTPBasicAuth(sn_username, sn_password))
        logger.info(f"ServiceNow update response status code: {response.status_code}")
        response.raise_for_status()
        logger.info(f"Incident updated successfully.")
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred while updating incident: {http_err}")
    except Exception as err:
        logger.error(f"Other error occurred while updating incident: {err}")

def process_incidents():
    while True:
        try:
            # Get the most recent incident from ServiceNow
            logger.info("Starting incident processing cycle.")
            most_recent_incident = get_most_recent_incident()
            if not most_recent_incident:
                logger.info("No incidents found.")
                time.sleep(5)
                continue

            description = most_recent_incident.get('description')
            incident_sys_id = most_recent_incident.get('sys_id')

            if not description:
                logger.info("No description found for the incident.")
                time.sleep(5)
                continue

            # Check if an existing playbook matches the incident description
            existing_playbook = search_existing_playbooks(description)
            if existing_playbook:
                logger.info("Found an existing playbook that matches the incident description.")
                update_incident_state(incident_sys_id, AWAITING_USER_INFO_STATE_ID, comment=f"Use the following playbook: {EXISTING_PLAYBOOKS_REPO_URL}")
                continue

            # Get playbook content from OpenAI based on incident description
            playbook_content = ask_openai(description)

            # Format the playbook content
            formatted_content = format_playbook_content(playbook_content)

            # Generate branch name
            branch_name = f"generated-playbook-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            file_path = "generated_playbook.yml"

            # Create a pull request
            pr_response = create_pull_request(branch_name, file_path, formatted_content)

            if pr_response:
                logger.info(f"Pull request created: {pr_response['html_url']}")
                # Update the incident state to "Awaiting User Info"
                update_incident_state(incident_sys_id, AWAITING_USER_INFO_STATE_ID)
            else:
                logger.error('Failed to create pull request.')

        except Exception as e:
            logger.error(f"Error processing request: {e}")

        # Sleep for 5 seconds before the next iteration
        time.sleep(5)

if __name__ == "__main__":
    process_incidents()
