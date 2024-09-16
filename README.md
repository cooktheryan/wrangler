# wrangler
A project that accepts text from Service now and generates playbooks to try to resolve the problems described in the body of the service now incident.

```
export GITHUB_TOKEN=sdafasdf
export SN_USERNAME=asfdasdf
export SN_PASSWORD=asdfasdf
export OPENAI_API_KEY=asfdaasdf
```

```
python3 -m venv env
source env/bin/activate
pip install openai requests gitpython
python3 app.py
```