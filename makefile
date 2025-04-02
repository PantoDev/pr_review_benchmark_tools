.PHONY: run-quality-analysis
run-quality-analysis:
	@if [ -z "$(pr_url)" ] && [ -z "$(file_path)" ]; then \
		echo "provide pr url or file path";\
		exit 1; \
	elif [ -n "$(pr_url)" ] && [ -n "$(file_path)" ]; then \
		echo "provide only one of them pr url or file path"; \
		exit 1; \
	fi
	python3 -m script $(if $(pr_url),--pr_url "$(pr_url)")  $(if $(file_path),--file_path "$(file_path)") --output csv
