.PHONY: lint lint-ansible lint-yaml run

lint: lint-ansible lint-yaml

lint-ansible:
	uv run ansible-lint .

lint-yaml:
	uv run yamllint -s .

run:
	uv run ansible-playbook playbooks/create-toponodes.yaml
